"""Split each UN Geodata row into its polygon parts."""

from pathlib import Path

from pipeline.config import write_parquet

from .common import connect, data, finish


def main() -> None:
    """Write one row per part, keeping the row's objectid and the part's index."""
    conn = connect()
    src = data("01", "un_polygons")
    query = f"""--sql
        SELECT objectid AS un_objectid, iso3cd AS un_iso3, d.path[1] AS un_part,
               d.geom AS geometry
        FROM (SELECT objectid, iso3cd, unnest(ST_Dump(geometry)) AS d FROM '{src}')
    """
    write_parquet(conn, query, Path(data("02", "un_parts")))
    finish(conn, "02", [Path(src)])
