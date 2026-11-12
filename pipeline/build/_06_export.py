"""Dissolve the units to the ADM0 output and the UN layer, and check them."""

import json
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING

from pipeline.config import write_parquet

from .common import (
    STEPS,
    changes,
    connect,
    curated_dir,
    data,
    finish,
    stage_dir,
    stages,
    unchanged,
)

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

logger = getLogger(__name__)

TOLERANCE = 1e-9
UN_ROWS = 264
PATH_OUTPUTS = {"errors": "path_errors", "split": "path_split"}
ADM0_KEY = "coalesce(adm0_id, entity)"


def _dissolve(key: str, units: str | None = None) -> str:
    return f"""--sql
        SELECT {key}, ST_Multi(ST_CollectionExtract(ST_Union_Agg(geometry), 3))
            AS geometry
        FROM '{units or data("05", "units")}' GROUP BY 1"""


def _sources(conn: DuckDBPyConnection, units: str, extra: tuple) -> None:
    """Add the entities changes and ``extra`` create to both sources, keyed by code."""
    rows = [
        (e["code"], e["name"], None, None) for c in changes() if (e := c.get("entity"))
    ]
    conn.execute(
        "CREATE TABLE entities (code VARCHAR, name VARCHAR, stscod SMALLINT, "
        "status_label VARCHAR)"
    )
    conn.executemany("INSERT INTO entities VALUES (?, ?, ?, ?)", [*rows, *extra])
    conn.execute(f"""--sql
        CREATE TABLE un_src AS
        SELECT 'UN ' || objectid AS key, * EXCLUDE geometry
        FROM '{data("01", "un_polygons")}'
        UNION ALL BY NAME
        SELECT 'NEW ' || code AS key, code AS iso3cd, name AS romnam, name AS maplab,
               stscod, status_label
        FROM entities;
        CREATE TABLE adm0_src AS
        SELECT {ADM0_KEY} AS key, any_value(coalesce(u.iso3, u.entity)) AS iso3,
               string_agg(DISTINCT n.iso3cd, ';' ORDER BY n.iso3cd) AS un_iso3,
               string_agg(DISTINCT u.un_owner::VARCHAR, ';'
                          ORDER BY u.un_owner::VARCHAR) AS un_objectid,
               string_agg(DISTINCT u.gaul_id, ';' ORDER BY u.gaul_id) AS gaul_id,
               string_agg(DISTINCT g.ISO3_CODE, ';' ORDER BY g.ISO3_CODE) AS gaul_code
        FROM '{units}' u
        LEFT JOIN '{data("01", "un_polygons")}' n ON n.objectid = u.un_owner
        LEFT JOIN '{data("01", "gaul_polygons")}' g USING (gaul_id)
        GROUP BY 1;
    """)


def exports(
    conn: DuckDBPyConnection, units: str, un: str, adm0: str, extra: tuple = ()
) -> None:
    """Dissolve ``units`` by key, adding (code, name, stscod, status) ``extra``."""
    _sources(conn, units, extra)
    for path, src, key, columns in (
        (un, "un_src", "coalesce('NEW ' || entity, 'UN ' || un_owner)", "s.*"),
        (adm0, "adm0_src", ADM0_KEY, "s.key AS adm0_id, s.*"),
    ):
        write_parquet(
            conn,
            f"""--sql
            SELECT {columns} EXCLUDE key, d.geometry
            FROM ({_dissolve(f"{key} AS key", units)}) d
            JOIN {src} s USING (key)""",
            Path(path),
        )


def _path_state(types: list[str]) -> str:
    """Return a dissolve showing the units once changes of ``types`` are applied."""
    picked = [c for c in changes() if c["type"] in types]
    applied = [c["id"] for c in picked if "relabel" not in c]
    generated = (
        " OR len(list_filter(ids, lambda x: x LIKE 'S-%')) > 0"
        if "group_split" in types
        else ""
    )
    relabels = "".join(
        f"""WHEN un_objectid = {r["un_objectid"]} AND gaul_id = '{r["gaul_id"]}'
                        THEN 'UN {r["to"]}' """
        for c in picked
        if (r := c.get("relabel"))
    )
    return f"""--sql
        WITH flagged AS (
            SELECT *, list_has_any(ids, {applied}){generated} AS applied
            FROM (SELECT *, string_split(coalesce(change_ids, ''), ';') AS ids
                  FROM '{data("05", "units")}')
        ),
        keyed AS (
            SELECT CASE WHEN gaul_id IS NULL THEN 'NEW ' || entity
                        WHEN applied OR (coalesce(change_ids, '') = '' AND gaul_id IN
                             (SELECT gaul_id FROM flagged WHERE applied))
                        THEN 'ADM0 ' || adm0_id {relabels}
                        ELSE 'UN ' || un_objectid END AS key,
                   geometry
            FROM flagged
        ),
        dissolved AS (
            SELECT key, ST_Multi(ST_CollectionExtract(ST_Union_Agg(geometry), 3))
                AS geometry
            FROM keyed GROUP BY key
        )
        SELECT d.key, a.* EXCLUDE key, u.* EXCLUDE key, d.geometry
        FROM dissolved d
        LEFT JOIN adm0_src a ON d.key = 'ADM0 ' || a.key
        LEFT JOIN un_src u ON d.key = u.key"""


def _path_outputs(conn: DuckDBPyConnection) -> None:
    """Write the state after each page step that neither export already shows."""
    types: list[str] = []
    for step, step_types in STEPS.items():
        types += step_types
        if step in PATH_OUTPUTS:
            name = PATH_OUTPUTS[step]
            write_parquet(conn, _path_state(types), Path(data("06", name)))


def _checks(conn: DuckDBPyConnection, un: str, adm0: str) -> dict:
    """Return each check's name, measured value and whether it passed."""
    units, parts = data("05", "units"), data("04", "parts")
    src_un, src_gaul = data("01", "un_polygons"), data("01", "gaul_polygons")

    def one(sql: str) -> object:
        return conn.execute(sql).fetchall()[0][0]

    difference = one(f"""--sql
        SELECT max(ST_Area(ST_SymDifference(ST_MakeValid(a.geometry),
                                            ST_MakeValid(b.geometry))))
        FROM ({_dissolve("un_objectid")}) a
        JOIN '{src_un}' b ON b.objectid = a.un_objectid""")
    described = {s["stage"] for s in stages() if s["summary"] and s["why"]}
    used = {
        c
        for (ids,) in conn.execute(f"SELECT change_ids FROM '{units}'").fetchall()
        for c in ids.split(";")
        if c
    }
    known = {c["id"] for c in changes()}
    adding = ", ".join(f"'{c['id']}'" for c in changes() if "entity" in c) or "''"
    return {
        "un_rows": (n := one(f"SELECT count(*) FROM '{un}'"), n == UN_ROWS),
        "un_max_difference": (difference, difference <= TOLERANCE),
        "adm0_ids_duplicated": (
            n := one(f"SELECT count(*) - count(DISTINCT adm0_id) FROM '{adm0}'"),
            n == 0,
        ),
        "gaul_entities_missing": (
            n := one(f"""--sql
                SELECT count(*) FROM '{src_gaul}'
                WHERE gaul_id NOT IN (SELECT gaul_id FROM '{units}'
                                      WHERE gaul_id IS NOT NULL)"""),
            n == 0,
        ),
        "fieldmaps_pieces_missing": (
            one(f"""--sql
                SELECT list(adm0_name ORDER BY adm0_name)
                FROM '{data("01", "fieldmaps_voronoi")}'
                WHERE adm0_id NOT IN (SELECT piece FROM '{parts}'
                                      WHERE piece IS NOT NULL)
                  AND iso_3 IN (SELECT split_part(piece, '_', 1) FROM '{parts}')"""),
            True,
        ),
        "units_invalid": (
            n := one(f"SELECT count(*) FROM '{units}' WHERE NOT ST_IsValid(geometry)"),
            n == 0,
        ),
        "area_difference": (
            d := abs(
                one(f"""--sql
                SELECT (SELECT sum(ST_Area(geometry)) FROM '{units}')
                     - (SELECT sum(ST_Area(geometry)) FROM '{src_un}')""")
            ),
            d <= TOLERANCE * 1000,
        ),
        "parts_without_gaul": (
            n := one(f"""--sql
                SELECT count(*) FROM '{parts}'
                WHERE gaul_id IS NULL AND coalesce(change_id, '') NOT IN ({adding})"""),
            n == 0,
        ),
        "unknown_changes": (
            n := len({c for c in used if c.startswith("C")} - known),
            n == 0,
        ),
        "undescribed_stages": (n := len(stages()) - len(described), n == 0),
    }


def main() -> None:
    """Write the ADM0 output and UN layer, then fail on any check that fails."""
    inputs = [
        Path(__file__),
        Path(data("05", "units")),
        curated_dir / "changes.json",
    ]
    if all(unchanged("06", p) for p in inputs):
        logger.info("stage 06: inputs unchanged")
        return
    conn = connect()
    un, adm0 = data("06", "un"), data("06", "adm0")
    exports(conn, data("05", "units"), un, adm0)
    _path_outputs(conn)
    checks = _checks(conn, un, adm0)
    (stage_dir("06") / "checks.json").write_text(
        json.dumps(
            {k: {"value": v, "passed": p} for k, (v, p) in checks.items()}, indent=2
        )
        + "\n"
    )
    finish(conn, "06", inputs)
    failed = [k for k, (_, passed) in checks.items() if not passed]
    if failed:
        msg = f"build checks failed: {failed}"
        raise ValueError(msg)
