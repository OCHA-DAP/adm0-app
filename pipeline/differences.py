"""Compare land boundaries and island groupings across sources on OSM land."""

from itertools import combinations
from logging import getLogger
from os import getenv
from time import perf_counter
from typing import TYPE_CHECKING

from . import review
from .config import (
    SOURCE_COLUMNS,
    layers,
    open_db,
    prepare_dir,
    register_dir,
    tmp_dir,
    write_parquet,
)

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

logger = getLogger(__name__)

VERTICES = 256
KM2 = "ST_Area_Spheroid({}) / 1e6"
VORONOI = {lyr["source"]: lyr["id"] for lyr in layers() if lyr["kind"] == "voronoi"}
LINES = [lyr["id"] for lyr in layers() if lyr["kind"] == "line"]
PAIRS = list(combinations(sorted(VORONOI), 2))


def _step(conn: DuckDBPyConnection, name: str, sql: str) -> None:
    start = perf_counter()
    conn.execute(sql)
    logger.info("%s: %.0fs", name, perf_counter() - start)


def _chunks(table: str, cols: str, src: str) -> str:
    """Subdivided parts of ``src`` with their envelopes, as ``table``."""
    return f"""--sql
        CREATE OR REPLACE TABLE {table} AS
        SELECT *, ST_Envelope(geom) AS env FROM (
            SELECT {cols}, unnest(ST_Dump(ST_Subdivide(geom, {VERTICES}))).geom AS geom
            FROM ({src}))
    """


def _land(conn: DuckDBPyConnection) -> None:
    """Split OSM land into land chunks crossed by any line and whole islands."""
    land = f"read_parquet('{prepare_dir / 'osm_land.parquet'}')"
    if bbox := getenv("DIFF_BBOX"):
        land = f"""(SELECT fid, ST_CollectionExtract(ST_Intersection(geometry,
            ST_MakeEnvelope({bbox})), 3) AS geometry FROM {land}
            WHERE ST_Intersects(geometry, ST_MakeEnvelope({bbox})))"""
    _step(
        conn,
        "land",
        f"""CREATE OR REPLACE TABLE land AS
        SELECT fid, geometry AS geom, ST_Envelope(geometry) AS env,
               {KM2.format("geometry")} AS km2
        FROM {land} WHERE NOT ST_IsEmpty(geometry)""",
    )
    lines = " UNION ALL ".join(
        f"SELECT geometry AS geom FROM read_parquet('{prepare_dir / name}.parquet')"
        for name in LINES
    )
    _step(conn, "segments", _chunks("segs", "1 AS one", lines))
    _step(
        conn,
        "candidates",
        """CREATE OR REPLACE TABLE candidates AS
        SELECT DISTINCT l.fid FROM land l JOIN segs s ON ST_Intersects(l.env, s.env)""",
    )
    _step(
        conn,
        "candidate chunks",
        _chunks(
            "chunks",
            "fid",
            "SELECT fid, geom FROM land JOIN candidates USING (fid)",
        ),
    )
    _step(
        conn,
        "crossed",
        """CREATE OR REPLACE TABLE crossed AS
        SELECT DISTINCT c.fid FROM chunks c JOIN segs s
          ON ST_Intersects(c.env, s.env) AND ST_Intersects(c.geom, s.geom)""",
    )
    conn.execute("""--sql
        DELETE FROM chunks WHERE fid NOT IN (SELECT fid FROM crossed);
        CREATE OR REPLACE TABLE chunks AS
        SELECT row_number() OVER () AS chunk, * FROM chunks;
        CREATE OR REPLACE TABLE islands AS
        SELECT fid, km2, ST_PointOnSurface(geom) AS pt FROM land
        WHERE fid NOT IN (SELECT fid FROM crossed);
    """)
    n = conn.execute(
        "SELECT (SELECT count(*) FROM crossed), (SELECT count(*) FROM islands)"
    ).fetchone()
    logger.info("land: %d crossed polygons, %d islands", *n)


def _assign(conn: DuckDBPyConnection, source: str) -> None:
    """Clip land chunks to ``source``'s cells and put each island in one cell."""
    c = SOURCE_COLUMNS[source]
    cells = f"""SELECT coalesce(({c["id"]})::VARCHAR, '') AS entity,
            ({c["code"]})::VARCHAR AS code,
            ({c.get("entity", c["name"])})::VARCHAR AS name,
            geometry AS geom
        FROM read_parquet('{prepare_dir / VORONOI[source]}.parquet')"""
    _step(conn, f"{source} cells", _chunks("cells", "entity, code, name", cells))
    conn.execute(f"""--sql
        INSERT INTO entities
        SELECT DISTINCT '{source}', entity, code, name FROM cells
    """)
    _step(
        conn,
        f"{source} pieces",
        f"""INSERT INTO pieces
        SELECT '{source}', k.chunk, c.entity, ST_CollectionExtract(
            ST_Intersection(k.geom, c.geom), 3)
        FROM chunks k JOIN cells c
          ON ST_Intersects(k.env, c.env) AND ST_Intersects(k.geom, c.geom)""",
    )
    _step(
        conn,
        f"{source} islands",
        f"""INSERT INTO placed
        SELECT '{source}', i.fid, any_value(c.entity)
        FROM islands i JOIN cells c ON ST_Intersects(i.pt, c.geom)
        GROUP BY i.fid""",
    )


def _overlay(conn: DuckDBPyConnection) -> None:
    """Overlay every source pair's pieces and islands, then mutual best matches."""
    conn.execute(
        "CREATE OR REPLACE TABLE overlay (a VARCHAR, b VARCHAR, "
        "a_entity VARCHAR, b_entity VARCHAR, km2 DOUBLE, geom GEOMETRY)"
    )
    for a, b in PAIRS:
        _step(
            conn,
            f"{a}|{b} overlay",
            f"""INSERT INTO overlay
            SELECT * EXCLUDE g, {KM2.format("g")}, g FROM (
                SELECT '{a}', '{b}', pa.entity, pb.entity,
                       ST_CollectionExtract(ST_Intersection(pa.geom, pb.geom), 3) AS g
                FROM pieces pa JOIN pieces pb USING (chunk)
                WHERE pa.source = '{a}' AND pb.source = '{b}'
                  AND ST_Intersects(pa.geom, pb.geom))
            WHERE NOT ST_IsEmpty(g)""",
        )
    conn.execute("""--sql
        CREATE OR REPLACE TABLE island_pairs AS
        SELECT pa.source AS a, pb.source AS b, i.fid, pa.entity AS a_entity,
               pb.entity AS b_entity, i.km2
        FROM islands i JOIN placed pa USING (fid) JOIN placed pb USING (fid)
        WHERE pa.source < pb.source;
        CREATE OR REPLACE TABLE weights AS
        SELECT a, b, a_entity, b_entity, sum(km2) AS km2 FROM (
            SELECT a, b, a_entity, b_entity, km2 FROM overlay
            UNION ALL SELECT a, b, a_entity, b_entity, km2 FROM island_pairs)
        GROUP BY ALL;
        CREATE OR REPLACE TABLE matches AS
        SELECT w.*,
            km2 = max(km2) OVER (PARTITION BY a, b, a_entity)
            AND km2 = max(km2) OVER (PARTITION BY a, b, b_entity) AS mutual
        FROM weights w;
    """)


def _named(side: str) -> str:
    return f"""LEFT JOIN entities {side}e
        ON {side}e.source = d.{side} AND {side}e.entity = d.{side}_entity"""


# A patch shows in the source whose entity has no mutual match in the other.
SIDE = """CASE WHEN pa.entity IS NULL AND pb.entity IS NOT NULL THEN 'a'
    WHEN pb.entity IS NULL AND pa.entity IS NOT NULL THEN 'b' ELSE 'both' END"""


def _sided() -> str:
    return " ".join(
        f"""LEFT JOIN paired p{x} ON p{x}.a = d.a AND p{x}.b = d.b
            AND p{x}.side = '{x}' AND p{x}.entity = d.{x}_entity"""
        for x in "ab"
    )


def _write(conn: DuckDBPyConnection) -> None:
    register_dir.mkdir(parents=True, exist_ok=True)
    conn.execute("""--sql
        CREATE OR REPLACE TABLE paired AS
        SELECT DISTINCT a, b, 'a' AS side, a_entity AS entity FROM matches WHERE mutual
        UNION SELECT DISTINCT a, b, 'b', b_entity FROM matches WHERE mutual
    """)
    cols = """d.a || '|' || d.b AS pair, d.a, d.b, d.a_entity, ae.code AS a_code,
        ae.name AS a_name, d.b_entity, be.code AS b_code, be.name AS b_name"""
    write_parquet(
        conn,
        f"SELECT {cols}, d.km2, d.mutual FROM matches d {_named('a')} {_named('b')}",
        register_dir / "matches.parquet",
        geo=False,
    )
    _step(
        conn,
        "land patches",
        f"""CREATE OR REPLACE TABLE land_diff AS
        SELECT {cols}, {SIDE} AS side, {KM2.format("geom")} AS km2, geom FROM (
            SELECT a, b, a_entity, b_entity, unnest(ST_Dump(g)).geom AS geom FROM (
                SELECT a, b, a_entity, b_entity, ST_Union_Agg(o.geom) AS g
                FROM overlay o JOIN matches m USING (a, b, a_entity, b_entity)
                WHERE NOT m.mutual GROUP BY ALL)) d {_named("a")} {_named("b")}
        {_sided()}""",
    )
    review.build(conn)
    write_parquet(
        conn,
        """SELECT * EXCLUDE (geom, lo, hi), geom AS geometry FROM land_review
        ORDER BY km2 DESC""",
        register_dir / "land.parquet",
    )
    sources = sorted(VORONOI)
    entity = ", ".join(
        f"""max(p.entity) FILTER (p.source = '{s}') AS {s}_entity,
            max(e.code) FILTER (p.source = '{s}') AS {s}_code,
            max(e.name) FILTER (p.source = '{s}') AS {s}_name"""
        for s in sources
    )
    write_parquet(
        conn,
        f"""SELECT i.fid, i.km2, {entity}, any_value(r.item) AS item
        FROM islands i JOIN placed p USING (fid)
        LEFT JOIN entities e USING (source, entity)
        LEFT JOIN item_islands r USING (fid)
        GROUP BY i.fid, i.km2 ORDER BY i.km2 DESC""",
        register_dir / "islands.parquet",
        geo=False,
    )
    write_parquet(
        conn,
        f"""SELECT pair, 'land' AS type, side, item, a_code, a_name, b_code, b_name,
                km2, geom AS geometry FROM land_review
        UNION ALL
        SELECT d.a || '|' || d.b, 'island', {SIDE}, r.item, ae.code, ae.name,
               be.code, be.name, d.km2, l.geom
        FROM island_pairs d JOIN matches m USING (a, b, a_entity, b_entity)
        JOIN land l USING (fid) LEFT JOIN item_islands r USING (fid)
        {_named("a")} {_named("b")} {_sided()}
        WHERE NOT m.mutual""",
        prepare_dir / "differences.parquet",
    )


def main() -> None:
    """Write land and island differences for every source pair."""
    conn = open_db(tmp_dir / "differences.duckdb")
    conn.execute("SET geometry_always_xy = true; SET preserve_insertion_order = false")
    conn.execute("""--sql
        CREATE TABLE entities (source VARCHAR, entity VARCHAR, code VARCHAR,
                               name VARCHAR);
        CREATE TABLE pieces (source VARCHAR, chunk BIGINT, entity VARCHAR,
                             geom GEOMETRY);
        CREATE TABLE placed (source VARCHAR, fid BIGINT, entity VARCHAR);
    """)
    _land(conn)
    for source in sorted(VORONOI):
        _assign(conn, source)
    _overlay(conn)
    _write(conn)
    conn.close()
