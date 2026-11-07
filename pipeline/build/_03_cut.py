"""Cut mainland parts with UN lines and the curated lines."""

from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING

from pipeline.config import write_parquet

from .common import changes, connect, curated_dir, data, finish

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

logger = getLogger(__name__)


def _cut_table(conn: DuckDBPyConnection) -> None:
    """Load one row per cut line and target polygon into ``cuts``."""
    un_lines = data("01", "un_lines")
    curated = curated_dir / "cut_lines.parquet"
    conn.execute("""--sql
        CREATE TABLE cuts (change_id VARCHAR, un_objectid BIGINT, area_id VARCHAR,
            source_layer VARCHAR, source_feature VARCHAR, geometry GEOMETRY)
    """)
    for change in changes():
        for target in change.get("cut", {}).get("un_objectids", []):
            ids = change["cut"].get("un_lines")
            if ids:
                conn.execute(f"""--sql
                    INSERT INTO cuts
                    SELECT '{change["id"]}', {target}, NULL, 'bndl',
                           'objectid ' || objectid, geometry
                    FROM '{un_lines}' WHERE objectid IN ({",".join(map(str, ids))})
                """)
            else:
                conn.execute(f"""--sql
                    INSERT INTO cuts
                    SELECT change_id, {target}, area_id, source_layer, source_feature,
                           geometry
                    FROM '{curated}' WHERE change_id = '{change["id"]}'
                """)


def main() -> None:
    """Polygonize each target's mainland with its cuts; other parts pass through."""
    conn = connect()
    parts = data("02", "un_parts")
    curated = curated_dir / "cut_lines.parquet"
    _cut_table(conn)
    conn.execute(f"""--sql
        CREATE TABLE mainland AS
        SELECT un_objectid, arg_max(un_part, ST_Area(geometry)) AS un_part
        FROM '{parts}' WHERE un_objectid IN (SELECT un_objectid FROM cuts)
        GROUP BY ALL
    """)
    conn.execute("""--sql
        CREATE TABLE faces (un_objectid BIGINT, un_part INTEGER, face INTEGER,
            area_id VARCHAR, geometry GEOMETRY)
    """)
    for objectid, part in conn.execute("SELECT * FROM mainland").fetchall():
        conn.execute(f"""--sql
            INSERT INTO faces
            WITH m AS (
                SELECT geometry AS p FROM '{parts}'
                WHERE un_objectid = {objectid} AND un_part = {part}
            ),
            noded AS (
                SELECT ST_Union_Agg(x) AS x FROM (
                    SELECT ST_Boundary(p) AS x FROM m
                    UNION ALL SELECT geometry FROM cuts WHERE un_objectid = {objectid})
            ),
            f AS (SELECT unnest(ST_Dump(ST_Polygonize([x]))).geom AS q FROM noded),
            inside AS (
                SELECT q, ST_PointOnSurface(q) AS pt FROM f, m
                WHERE ST_Within(ST_PointOnSurface(q), p)
            )
            SELECT {objectid}, {part}, row_number() OVER (ORDER BY ST_Area(q) DESC),
                (SELECT any_value(area_id) FROM cuts
                 WHERE un_objectid = {objectid} AND area_id IS NOT NULL
                   AND ST_Within(pt, ST_MakePolygon(geometry))),
                q
            FROM inside
        """)
    query = f"""--sql
        SELECT p.un_objectid, p.un_iso3, p.un_part, coalesce(f.face, 0) AS face,
               f.area_id, coalesce(f.geometry, p.geometry) AS geometry
        FROM '{parts}' p
        LEFT JOIN faces f USING (un_objectid, un_part)
    """
    write_parquet(conn, query, Path(data("03", "faces")))
    write_parquet(conn, "SELECT * FROM cuts", Path(data("03", "cuts")))
    finish(conn, "03", [Path(parts), curated, curated_dir / "changes.json"])
