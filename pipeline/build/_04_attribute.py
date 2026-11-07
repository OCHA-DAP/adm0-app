"""Give every piece one GAUL entity, then record GAUL land left without a piece."""

from pathlib import Path

from pipeline.config import write_parquet

from .common import BIT_VERTICES, KM2, changes, connect, curated_dir, data, finish


def main() -> None:
    """Attribute pieces by overlap, then cell or UN owner, then overrides."""
    conn = connect()
    faces, gaul = data("03", "faces"), data("01", "gaul_polygons")
    cells, bits = data("01", "gaul_voronoi"), data("01", "gaul_bits")
    overrides = curated_dir / "island_overrides.csv"
    conn.execute(f"""--sql
        CREATE TABLE f AS SELECT row_number() OVER () AS fid, * FROM '{faces}';
        CREATE TABLE g AS
            SELECT gaul_id, ISO3_CODE AS iso3, d.path, d.geom AS geom FROM (
                SELECT gaul_id, ISO3_CODE,
                       unnest(ST_Dump(ST_MakeValid(geometry))) AS d FROM '{gaul}')
            WHERE ST_Dimension(d.geom) = 2;
        CREATE TEMP TABLE face_bits AS
            SELECT fid, unnest(ST_Dump(ST_Subdivide(
                       geometry, {BIT_VERTICES}))).geom AS geom
            FROM f;
        CREATE TEMP TABLE gaul_bits AS FROM '{bits}';
        CREATE TEMP TABLE hits AS
            SELECT b.fid, g.gaul_id, g.path, b.geom AS a, g.geometry AS b
            FROM face_bits b JOIN gaul_bits g ON ST_Intersects(b.geom, g.geometry);
        CREATE TABLE ov AS
            SELECT fid, gaul_id, sum(ST_Area(ST_Intersection(a, b))) AS a
            FROM hits GROUP BY ALL;
        CREATE TABLE best AS
            SELECT fid, arg_max(gaul_id, a) AS gaul_id, max(a) AS a FROM ov
            WHERE a > 0 GROUP BY fid;
        CREATE TEMP TABLE unmatched AS
            SELECT fid, ST_PointOnSurface(geometry) AS point FROM f
            WHERE fid NOT IN (SELECT fid FROM best);
        CREATE TABLE cell AS
            SELECT u.fid, c.gaul_id FROM unmatched u
            JOIN '{cells}' c ON ST_Intersects(u.point, c.geometry);
        CREATE TABLE o AS SELECT * FROM read_csv('{overrides}', types={{
            'un_objectid': 'BIGINT', 'un_part': 'INTEGER', 'face': 'INTEGER',
            'gaul_id': 'VARCHAR', 'change_id': 'VARCHAR', 'reason': 'VARCHAR'}});
        CREATE TABLE pair AS
            SELECT f.un_objectid, b.gaul_id, sum(b.a) AS a
            FROM best b JOIN f USING (fid) GROUP BY ALL;
        CREATE TABLE owner AS
            SELECT un_objectid, arg_max(gaul_id, a) AS gaul_id FROM pair
            GROUP BY un_objectid;
    """)
    conn.executemany(
        "INSERT INTO pair VALUES (?, ?, 0)",
        [key for c in changes() for key in c.get("keys", [])],
    )
    # A cell only counts where GAUL already links the two, or it is that entity's land.
    conn.execute("""--sql
        CREATE TABLE cell_owner AS
            SELECT c.fid, n.gaul_id FROM cell c
            JOIN f USING (fid) JOIN owner n USING (un_objectid)
            WHERE (f.un_objectid, c.gaul_id) NOT IN
                  (SELECT un_objectid, gaul_id FROM pair)
              AND c.gaul_id IN (SELECT gaul_id FROM best);
    """)
    query = """--sql
        SELECT f.un_objectid, f.un_iso3, f.un_part, f.face, f.area_id,
               coalesce(o.gaul_id, b.gaul_id, w.gaul_id, c.gaul_id) AS gaul_id,
               CASE WHEN o.gaul_id IS NOT NULL THEN 'override'
                    WHEN b.gaul_id IS NOT NULL THEN 'overlap'
                    WHEN w.gaul_id IS NOT NULL THEN 'un_owner'
                    WHEN c.gaul_id IS NOT NULL THEN 'cell' END AS rule,
               coalesce(b.gaul_id, w.gaul_id, c.gaul_id) AS gaul_id_before_override,
               round(coalesce(b.a, 0) / ST_Area(f.geometry), 4) AS overlap_share,
               o.change_id, o.reason, f.geometry
        FROM f
        LEFT JOIN best b USING (fid)
        LEFT JOIN cell c USING (fid)
        LEFT JOIN cell_owner w USING (fid)
        LEFT JOIN o ON o.un_objectid = f.un_objectid
            AND (o.un_part IS NULL OR o.un_part = f.un_part)
            AND (o.face IS NULL OR o.face = f.face)
    """
    write_parquet(conn, query, Path(data("04", "parts")))
    query = f"""--sql
        SELECT gaul_id, iso3, {KM2.format("geom")} AS km2, geom AS geometry FROM g
        WHERE (gaul_id, path) NOT IN (SELECT gaul_id, path FROM hits)
    """
    write_parquet(conn, query, Path(data("04", "removed")))
    finish(conn, "04", [Path(faces), Path(gaul), Path(cells), Path(bits), overrides])
