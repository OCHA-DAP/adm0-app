"""Write a dot per small polygon part of each source feature, to show tiny islands."""

from logging import getLogger
from typing import TYPE_CHECKING

from .config import layers, open_db, prepare_dir, tmp_dir, write_parquet

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

logger = getLogger(__name__)

# A part's dot stays until it is as wide as the dot (8 px on 512 px tiles); parts that
# wide at zoom 0 never get one.
DOT_PX = 8
WIDEST = DOT_PX * 360 / 512
REACH = 5


def _parts(conn: DuckDBPyConnection, layer: dict) -> None:
    """Stream the parts of one layer that are narrower than a dot at zoom 0."""
    out = tmp_dir / f"dots_{layer['id']}.parquet"
    conn.execute(f"""--sql
        COPY (
            SELECT '{layer["id"]}' AS layer, code, name,
                ST_XMin(d.geom) AS x0, ST_XMax(d.geom) AS x1,
                ST_YMin(d.geom) AS y0, ST_YMax(d.geom) AS y1, ST_Area(d.geom) AS area,
                d.geom AS geom
            -- A lateral unnest would copy each feature's geometry into every part row.
            FROM (SELECT upper(({layer["code"]})::VARCHAR) AS code,
                    ({layer["name"]})::VARCHAR AS name, unnest(ST_Dump(geometry)) AS d
                FROM read_parquet('{prepare_dir / layer["id"]}.parquet'))
            WHERE greatest(x1 - x0, y1 - y0) < {WIDEST}
        ) TO '{out}' (FORMAT PARQUET)
    """)


def main() -> None:
    """Write feature_dots.parquet for every polygon layer."""
    conn = open_db()
    conn.execute("SET memory_limit = '4GB'; SET threads = 4")
    conn.execute("SET preserve_insertion_order = false")
    polygons = [lyr for lyr in layers() if lyr["kind"] == "polygon"]
    for layer in polygons:
        _parts(conn, layer)
        logger.info("%s: parts written", layer["id"])
    files = ", ".join(f"'{tmp_dir}/dots_{lyr['id']}.parquet'" for lyr in polygons)
    # Each feature gets its own x offset, so the R-tree join never pairs two features.
    conn.execute(f"""--sql
        CREATE TABLE parts AS
        SELECT row_number() OVER () AS id, *, greatest(x1 - x0, y1 - y0) AS w,
            {REACH} * w AS reach,
            (x0 + x1) / 2 AS cx, (y0 + y1) / 2 AS cy,
            dense_rank() OVER (ORDER BY layer, code, name) * 2000 AS off
        FROM read_parquet([{files}])
    """)
    conn.execute("""--sql
        CREATE TABLE blocked AS
        WITH pairs AS MATERIALIZED (
            SELECT s.id AS sid, s.area AS sa, b.id AS bid, b.area AS ba
            FROM parts s JOIN parts b ON ST_Intersects(
                ST_MakeEnvelope(b.off + b.x0 - b.reach, b.y0 - b.reach,
                                b.off + b.x1 + b.reach, b.y1 + b.reach),
                ST_Point(s.off + s.cx, s.cy)))
        SELECT DISTINCT sid AS id FROM pairs WHERE ba > sa OR (ba = sa AND bid < sid)
    """)
    # A part needs no dot of its own near a larger dotted part of its feature.
    write_parquet(
        conn,
        f"""SELECT layer, code, name,
            log2({WIDEST} / greatest(w, 1e-9)) AS z,
            ST_MaximumInscribedCircle(geom).center AS geometry
        FROM parts WHERE id NOT IN (SELECT id FROM blocked)""",
        prepare_dir / "feature_dots.parquet",
    )
