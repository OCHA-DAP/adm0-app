"""Give every piece the GAUL entity its UN entity links to, or a change's.

A change that adds an entity leaves its pieces with no GAUL entity.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from pipeline.config import write_parquet

from .common import changes, connect, curated_dir, data, finish

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection


def _pieces(conn: DuckDBPyConnection) -> None:
    """Tag parts of codes FieldMaps splits with the cell of that code holding them."""
    decisions = curated_dir / "review_decisions.csv"
    splits = [c["id"] for c in changes() if c["type"] == "split"]
    conn.execute(f"""--sql
        CREATE TABLE fm AS
        SELECT iso_3 AS code, adm0_id AS piece, ST_MakeValid(geometry) AS geom
        FROM '{data("01", "fieldmaps_voronoi")}'
        WHERE iso_3 IN (
            SELECT iso_3 FROM '{data("01", "fieldmaps_voronoi")}'
            GROUP BY 1 HAVING count(DISTINCT adm0_id) > 1)
          AND iso_3 NOT IN (
            SELECT un FROM read_csv('{decisions}') WHERE action = 'whole');
        CREATE TABLE pts AS
        SELECT un_objectid, un_part, face, un_iso3,
               ST_PointOnSurface(geometry) AS pt
        FROM attributed
        WHERE un_iso3 IN (SELECT code FROM fm)
          AND (rule = 'link' OR change_id IN (SELECT unnest({splits or [""]})));
        CREATE TABLE inside AS
        SELECT p.un_objectid, p.un_part, p.face, p.un_iso3, f.code, f.piece
        FROM pts p JOIN fm f ON ST_Intersects(p.pt, f.geom);
        CREATE TABLE tagged_pieces AS
        SELECT un_objectid, un_part, face, min(piece) AS piece FROM inside
        WHERE code = un_iso3 GROUP BY ALL;
        INSERT INTO tagged_pieces
        SELECT p.un_objectid, p.un_part, p.face,
               arg_min(f.piece, ST_Distance(p.pt, f.geom))
        FROM pts p ANTI JOIN tagged_pieces t USING (un_objectid, un_part, face)
        JOIN fm f ON f.code = p.un_iso3
        GROUP BY ALL;
    """)


def main() -> None:
    """Look up each piece's override, then its area's change, then its link."""
    conn = connect()
    conn.execute(
        "CREATE TABLE area_keys (un_objectid BIGINT, area_id VARCHAR, "
        "gaul_id VARCHAR, change_id VARCHAR)"
    )
    conn.executemany(
        "INSERT INTO area_keys VALUES (?, ?, ?, ?)",
        [
            (un, area, gaul, c["id"])
            for c in changes()
            for un, gaul in c.get("keys", [])
            for area in c.get("areas", [])
        ],
    )
    faces = data("03", "faces")
    links = curated_dir / "gaul_links.csv"
    overrides = curated_dir / "island_overrides.csv"
    conn.execute(f"""--sql
        CREATE TABLE attributed AS
        SELECT f.un_objectid, f.un_iso3, f.un_part, f.face, f.area_id,
               CASE WHEN o.change_id IS NOT NULL THEN o.gaul_id
                    WHEN a.change_id IS NOT NULL THEN a.gaul_id ELSE l.gaul_id END
                   AS gaul_id,
               CASE WHEN o.change_id IS NOT NULL THEN 'override'
                    WHEN a.change_id IS NOT NULL THEN 'area' ELSE 'link' END
                   AS rule,
               coalesce(o.change_id, a.change_id) AS change_id, o.reason, f.geometry
        FROM '{faces}' f
        LEFT JOIN read_csv('{links}', types={{
            'un_objectid': 'BIGINT', 'gaul_id': 'VARCHAR'}}) l USING (un_objectid)
        LEFT JOIN read_csv('{overrides}', types={{
            'un_objectid': 'BIGINT', 'un_part': 'INTEGER', 'face': 'INTEGER',
            'gaul_id': 'VARCHAR', 'change_id': 'VARCHAR', 'reason': 'VARCHAR'}}) o
            ON o.un_objectid = f.un_objectid
            AND (o.un_part IS NULL OR o.un_part = f.un_part)
            AND (o.face IS NULL OR o.face = f.face)
        LEFT JOIN area_keys a
            ON a.un_objectid = f.un_objectid AND a.area_id = f.area_id
    """)
    _pieces(conn)
    query = """--sql
        SELECT a.* EXCLUDE (geometry), t.piece, a.geometry
        FROM attributed a
        LEFT JOIN tagged_pieces t USING (un_objectid, un_part, face)
    """
    write_parquet(conn, query, Path(data("04", "parts")))
    finish(
        conn,
        "04",
        [
            Path(faces),
            links,
            overrides,
            curated_dir / "changes.json",
            curated_dir / "review_decisions.csv",
            Path(data("01", "fieldmaps_voronoi")),
        ],
    )
