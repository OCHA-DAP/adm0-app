"""Dissolve the units to both exports and check them against the sources."""

import json
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING

from pipeline.config import write_parquet

from .common import (
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
UN_ROWS, GAUL_ROWS = 264, 276
PATH_OUTPUTS = {"errors": "path_errors", "disputed": "path_disputed"}


def _dissolve(key: str) -> str:
    return f"""--sql
        SELECT {key}, ST_Multi(ST_CollectionExtract(ST_Union_Agg(geometry), 3))
            AS geometry
        FROM '{data("05", "units")}' GROUP BY 1"""


def _sources(conn: DuckDBPyConnection) -> None:
    """Add the entities changes create to both sources, keyed like the dissolves."""
    rows = [(e["code"], e["name"]) for c in changes() if (e := c.get("entity"))]
    conn.execute("CREATE TABLE entities (code VARCHAR, name VARCHAR)")
    conn.executemany("INSERT INTO entities VALUES (?, ?)", rows)
    units = data("05", "units")
    conn.execute(f"""--sql
        CREATE TABLE un_src AS
        SELECT 'UN ' || objectid AS key, * EXCLUDE geometry
        FROM '{data("01", "un_polygons")}'
        UNION ALL BY NAME
        SELECT 'NEW ' || code AS key, code AS iso3cd, name AS romnam, name AS maplab
        FROM entities;
        CREATE TABLE gaul_src AS
        SELECT 'GAUL ' || gaul_id AS key, * EXCLUDE geometry
        FROM '{data("01", "gaul_polygons")}'
        UNION ALL BY NAME
        SELECT 'NEW ' || code AS key, code AS ISO3_CODE, code AS MAP_CODE,
               name AS GAUL0_NAME
        FROM entities
        WHERE code IN (SELECT entity FROM '{units}' WHERE gaul_id IS NULL);
    """)


def _path_state(types: list[str]) -> str:
    """Return a dissolve showing the units once changes of ``types`` are applied."""
    picked = [c for c in changes() if c["type"] in types]
    applied = [c["id"] for c in picked if "relabel" not in c]
    relabels = "".join(
        f"""WHEN un_objectid = {r["un_objectid"]} AND gaul_id = '{r["gaul_id"]}'
                        THEN 'UN {r["to"]}' """
        for c in picked
        if (r := c.get("relabel"))
    )
    return f"""--sql
        WITH flagged AS (
            SELECT *, list_has_any(string_split(coalesce(change_ids, ''), ';'),
                                   {applied}) AS applied
            FROM '{data("05", "units")}'
        ),
        keyed AS (
            SELECT CASE WHEN gaul_id IS NULL THEN 'NEW ' || entity
                        WHEN applied OR (coalesce(change_ids, '') = '' AND gaul_id IN
                             (SELECT gaul_id FROM flagged WHERE applied))
                        THEN 'GAUL ' || gaul_id {relabels}
                        ELSE 'UN ' || un_objectid END AS key,
                   geometry
            FROM flagged
        ),
        dissolved AS (
            SELECT key, ST_Multi(ST_CollectionExtract(ST_Union_Agg(geometry), 3))
                AS geometry
            FROM keyed GROUP BY key
        )
        SELECT d.key, g.* EXCLUDE key, u.* EXCLUDE key, d.geometry
        FROM dissolved d
        LEFT JOIN gaul_src g ON d.key = g.key
        LEFT JOIN un_src u ON d.key = u.key"""


def _path_outputs(conn: DuckDBPyConnection) -> None:
    """Write the state after each page step that neither export already shows."""
    steps = json.loads((curated_dir / "path.json").read_text())
    types: list[str] = []
    for step in steps:
        types += step["types"]
        if step["id"] in PATH_OUTPUTS:
            name = PATH_OUTPUTS[step["id"]]
            write_parquet(conn, _path_state(types), Path(data("06", name)))


def _checks(conn: DuckDBPyConnection, un: str, gaul: str) -> dict:
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
        "gaul_rows": (n := one(f"SELECT count(*) FROM '{gaul}'"), n == GAUL_ROWS),
        "gaul_attributes_differ": (
            n := one(f"""--sql
                SELECT count(*) FROM '{src_gaul}' s
                LEFT JOIN '{gaul}' e USING (gaul_id)
                WHERE e.gaul_id IS NULL
                   OR (s.GAUL0_CODE, s.ISO3_CODE, s.MAP_CODE, s.GAUL0_NAME,
                       s.CONTINENT) IS DISTINCT FROM (e.GAUL0_CODE, e.ISO3_CODE,
                       e.MAP_CODE, e.GAUL0_NAME, e.CONTINENT)"""),
            n == 0,
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
        "undescribed_changes": (
            n := sum(1 for c in changes() if not c["description"]),
            n == 0,
        ),
        "undescribed_stages": (n := len(stages()) - len(described), n == 0),
    }


def main() -> None:
    """Write the UN and GAUL exports, then fail on any check that does not pass."""
    inputs = [
        Path(__file__),
        Path(data("05", "units")),
        curated_dir / "changes.json",
        curated_dir / "path.json",
    ]
    if all(unchanged("06", p) for p in inputs):
        logger.info("stage 06: inputs unchanged")
        return
    conn = connect()
    un, gaul = data("06", "un"), data("06", "gaul")
    _sources(conn)
    for path, src, key in (
        (un, "un_src", "coalesce('NEW ' || entity, 'UN ' || un_owner)"),
        (gaul, "gaul_src", "coalesce('GAUL ' || gaul_id, 'NEW ' || entity)"),
    ):
        write_parquet(
            conn,
            f"""--sql
            SELECT s.* EXCLUDE key, d.geometry
            FROM ({_dissolve(f"{key} AS key")}) d
            JOIN {src} s USING (key)""",
            Path(path),
        )
    _path_outputs(conn)
    checks = _checks(conn, un, gaul)
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
