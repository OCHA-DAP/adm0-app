"""Snapshot the source layers every later stage reads."""

from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING

from pipeline.config import prepare_dir, write_parquet

from .common import BIT_VERTICES, KM2, connect, data, finish, unchanged

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

logger = getLogger(__name__)

SOURCES = {
    "un_polygons": "ungeodata_polygons",
    "un_lines": "ungeodata_lines",
    "gaul_polygons": "gaul_l0",
    "gaul_voronoi": "gaul_voronoi",
    "fieldmaps_voronoi": "fieldmaps_voronoi",
}


def _subdivided(rows: str) -> str:
    return f"""--sql
        SELECT * EXCLUDE geom,
               unnest(ST_Dump(ST_Subdivide(geom, {BIT_VERTICES}))).geom AS geometry
        FROM ({rows})"""


def _line_overlaps(conn: DuckDBPyConnection) -> None:
    """Write GAUL's small pieces, and the land GAUL and UN give different entities."""
    gaul_parts = f"""--sql
        SELECT gaul_id, ISO3_CODE AS code, d.path, d.geom FROM (
            SELECT gaul_id, ISO3_CODE, unnest(ST_Dump(ST_MakeValid(geometry))) AS d
            FROM '{data("01", "gaul_polygons")}')
        WHERE ST_Dimension(d.geom) = 2"""
    un_parts = f"""--sql
        SELECT iso3cd AS code, ST_MakeValid(geometry) AS geom
        FROM '{data("01", "un_polygons")}'"""
    conn.execute(f"""--sql
        CREATE TEMP TABLE gaul_bits AS {_subdivided(gaul_parts)};
        CREATE TEMP TABLE un_bits AS {_subdivided(un_parts)};
        CREATE TEMP TABLE touching AS
        SELECT g.code AS a_code, u.code AS b_code,
               g.geometry AS a_geom, u.geometry AS b_geom
        FROM gaul_bits g JOIN un_bits u ON ST_Intersects(g.geometry, u.geometry);
        CREATE TEMP TABLE shared AS
        SELECT a_code, b_code, ST_Intersection(a_geom, b_geom) AS geom
        FROM touching WHERE upper(a_code) <> upper(b_code);
    """)
    write_parquet(conn, "FROM gaul_bits", Path(data("01", "gaul_bits")))
    query = f"""--sql
        SELECT a_code, b_code, {KM2.format("geometry")} AS km2, geometry
        FROM (SELECT a_code, b_code,
                     unnest(ST_Dump(ST_Union_Agg(geom))).geom AS geometry
              FROM shared WHERE ST_Dimension(geom) = 2 GROUP BY a_code, b_code)
        WHERE ST_Dimension(geometry) = 2"""
    write_parquet(conn, query, Path(data("01", "line_overlaps")))


def main() -> None:
    """Copy each source into the stage folder and overlap GAUL with UN Geodata."""
    paths = [prepare_dir / f"{src}.parquet" for src in SOURCES.values()]
    if all(unchanged("01", p) for p in [Path(__file__), *paths]):
        logger.info("stage 01: inputs unchanged")
        return
    conn = connect()
    for name, path in zip(SOURCES, paths, strict=True):
        write_parquet(conn, f"SELECT * FROM '{path}'", Path(data("01", name)))
    _line_overlaps(conn)
    finish(conn, "01", [Path(__file__), *paths])
