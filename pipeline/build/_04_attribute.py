"""Give every piece the GAUL entity its UN entity links to, or a change's.

A change that adds an entity leaves its pieces with no GAUL entity.
"""

from pathlib import Path

from pipeline.config import write_parquet

from .common import changes, connect, curated_dir, data, finish


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
    query = f"""--sql
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
    """
    write_parquet(conn, query, Path(data("04", "parts")))
    finish(conn, "04", [Path(faces), links, overrides, curated_dir / "changes.json"])
