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
UN_ROWS, GAUL_ROWS = 260, 272
PATH_OUTPUTS = {"errors": "path_errors", "disputed": "path_disputed"}


def _dissolve(key: str) -> str:
    return f"""--sql
        SELECT {key}, ST_Multi(ST_CollectionExtract(ST_Union_Agg(geometry), 3))
            AS geometry
        FROM '{data("05", "units")}' GROUP BY {key}"""


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
            SELECT CASE WHEN applied OR (coalesce(change_ids, '') = '' AND gaul_id IN
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
        SELECT d.key, g.* EXCLUDE geometry, u.* EXCLUDE geometry, d.geometry
        FROM dissolved d
        LEFT JOIN '{data("01", "gaul_polygons")}' g ON d.key = 'GAUL ' || g.gaul_id
        LEFT JOIN '{data("01", "un_polygons")}' u ON d.key = 'UN ' || u.objectid"""


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
        FROM '{un}' a JOIN '{src_un}' b USING (objectid)""")
    described = {s["stage"] for s in stages() if s["summary"] and s["why"]}
    used = {
        c
        for row in conn.execute(f"FROM '{units}'").fetchall()
        for c in row[5].split(";")
        if c
    }
    known = {c["id"] for c in changes()}
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
            n := one(f"SELECT count(*) FROM '{parts}' WHERE gaul_id IS NULL"),
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
    write_parquet(
        conn,
        f"""--sql
        SELECT s.* EXCLUDE geometry, d.geometry
        FROM ({_dissolve("un_objectid")}) d
        JOIN '{data("01", "un_polygons")}' s ON s.objectid = d.un_objectid""",
        Path(un),
    )
    write_parquet(
        conn,
        f"""--sql
        SELECT s.* EXCLUDE geometry, d.geometry
        FROM ({_dissolve("gaul_id")}) d
        JOIN '{data("01", "gaul_polygons")}' s USING (gaul_id)""",
        Path(gaul),
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
