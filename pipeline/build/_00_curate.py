"""Write the cut lines UN Geodata lacks, from GAUL, into ``inputs/build/``."""

from pipeline.config import prepare_dir, write_parquet

from .common import connect, curated_dir

GAUL = prepare_dir / "gaul_l0.parquet"
GAUL_LINES = prepare_dir / "gaul_lines.parquet"
UN = prepare_dir / "ungeodata_polygons.parquet"
CHN, DISPUTED = 704, "238"
# GAUL's India-China line between Nepal and Bhutan is the only one east of 88E.
SIKKIM_XMIN = 88


def main() -> None:
    """Build the four Disputed Area rings and the Sikkim line."""
    conn = connect()
    curated_dir.mkdir(parents=True, exist_ok=True)
    query = f"""--sql
        WITH rings AS (
            SELECT row_number() OVER (ORDER BY ST_Area(d.geom) DESC) AS n,
                   ST_ExteriorRing(d.geom) AS geometry
            FROM (SELECT unnest(ST_Dump(geometry)) AS d FROM '{GAUL}'
                  WHERE gaul_id = '{DISPUTED}')
        ),
        mainland AS (
            SELECT ST_Boundary(d.geom) AS edge
            FROM (SELECT unnest(ST_Dump(geometry)) AS d FROM '{UN}'
                  WHERE objectid = {CHN})
            ORDER BY ST_Area(d.geom) DESC LIMIT 1
        ),
        sikkim AS (
            SELECT d.geom AS line
            FROM (SELECT unnest(ST_Dump(geometry)) AS d FROM '{GAUL_LINES}'
                  WHERE iso3_1 = 'CHN' AND iso3_2 = 'IND')
            WHERE ST_XMin(d.geom) > {SIKKIM_XMIN}
        )
        SELECT 'C04' AS change_id, 'xxx-' || n AS area_id,
               'gaul_l0' AS source_layer,
               'gaul_id {DISPUTED}, part ' || n AS source_feature,
               geometry
        FROM rings
        UNION ALL
        SELECT 'C05', NULL, 'gaul_lines', 'gaul_id 234 and 240, east of 88E',
               ST_Multi(ST_Collect([line,
                   ST_ShortestLine(ST_StartPoint(line), edge),
                   ST_ShortestLine(ST_EndPoint(line), edge)]))
        FROM sikkim, mainland
    """
    write_parquet(conn, query, curated_dir / "cut_lines.parquet")
