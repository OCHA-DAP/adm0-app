"""Compare land boundaries on OSM land, and each source's islands in other cells."""

from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from logging import getLogger
from os import getenv
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

from . import review
from .config import (
    SOURCE_COLUMNS,
    THREADS,
    fresh,
    layers,
    open_db,
    prepare_dir,
    record,
    register_dir,
    tiles_dir,
    tmp_dir,
    write_parquet,
)

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

logger = getLogger(__name__)

# An island gets no dot within this many of its widths of a larger island in its item.
REACH = 5

VERTICES = 256
KM2 = "ST_Area_Spheroid({}) / 1e6"
VORONOI = {lyr["source"]: lyr["id"] for lyr in layers() if lyr["kind"] == "voronoi"}
LINES = [lyr["id"] for lyr in layers() if lyr["kind"] == "line"]
POLYGONS = {lyr["source"]: lyr["id"] for lyr in layers() if lyr["kind"] == "polygon"}
# Row slices per thread, so the largest geometries don't queue behind each other.
SLICES = 4 * THREADS


def _step(conn: DuckDBPyConnection, name: str, sql: str) -> None:
    start = perf_counter()
    conn.execute(sql)
    logger.info("%s: %.0fs", name, perf_counter() - start)


def _entity_name(source: str) -> str:
    columns = SOURCE_COLUMNS[source]
    return columns.get("entity", columns["name"])


def _parallel(conn: DuckDBPyConnection, statements: list[str]) -> None:
    """Run ``statements`` side by side, each on its own cursor."""
    with ThreadPoolExecutor(THREADS) as pool:
        list(pool.map(lambda sql: conn.cursor().execute(sql), statements))


def _chunks(conn: DuckDBPyConnection, name: str, table: str, src: str) -> None:
    """Write ``src``'s rows to ``table``, subdivided, with envelopes, slice by slice."""
    start = perf_counter()
    # One statement over a few hundred large rows would run on one thread.
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE chunk_rows AS
        SELECT *, row_number() OVER (ORDER BY ST_NPoints(geom) DESC) % {SLICES} AS slice
        FROM ({src});
        CREATE OR REPLACE TABLE {table} AS
        SELECT * EXCLUDE slice, geom AS env FROM chunk_rows LIMIT 0
    """)
    _parallel(
        conn,
        [
            f"""INSERT INTO {table} BY NAME
            SELECT * EXCLUDE (geom, part, slice), part AS geom,
                ST_Envelope(part) AS env
            FROM (SELECT *, unnest(ST_Dump(ST_Subdivide(geom, {VERTICES}))).geom AS part
                FROM chunk_rows WHERE slice = {i})"""
            for i in range(SLICES)
        ],
    )
    conn.execute("DROP TABLE chunk_rows")
    logger.info("%s: %.0fs", name, perf_counter() - start)


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
    _chunks(conn, "segments", "segs", lines)
    _step(
        conn,
        "candidates",
        """CREATE OR REPLACE TABLE candidates AS
        SELECT DISTINCT l.fid FROM land l JOIN segs s ON ST_Intersects(l.env, s.env)""",
    )
    _chunks(
        conn,
        "candidate chunks",
        "chunks",
        "SELECT fid, geom FROM land JOIN candidates USING (fid)",
    )
    _step(
        conn,
        "crossed",
        """CREATE OR REPLACE TABLE crossed AS
        SELECT DISTINCT c.fid FROM chunks c JOIN segs s
          ON ST_Intersects(c.env, s.env) AND ST_Intersects(c.geom, s.geom)""",
    )
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE chunks AS
        SELECT row_number() OVER () AS chunk, *, {KM2.format("geom")} AS km2
        FROM chunks WHERE fid IN (SELECT fid FROM crossed);
        CREATE OR REPLACE TABLE islands AS
        SELECT fid, km2, ST_PointOnSurface(geom) AS pt FROM land
        WHERE fid NOT IN (SELECT fid FROM crossed);
    """)
    n = conn.execute(
        "SELECT (SELECT count(*) FROM crossed), (SELECT count(*) FROM islands)"
    ).fetchall()[0]
    logger.info("land: %d crossed polygons, %d islands", *n)


def _polygons(conn: DuckDBPyConnection) -> None:
    """Load every source's polygon parts and each entity's area and extent."""
    conn.execute("""--sql
        CREATE OR REPLACE TABLE polygon_parts (source VARCHAR, entity VARCHAR,
            code VARCHAR, name VARCHAR, geom GEOMETRY, env GEOMETRY)
    """)
    start = perf_counter()
    _parallel(
        conn,
        [
            f"""INSERT INTO polygon_parts
            SELECT *, ST_Envelope(geom) FROM (
                SELECT '{s}', coalesce(({SOURCE_COLUMNS[s]["id"]})::VARCHAR, ''),
                    ({SOURCE_COLUMNS[s]["code"]})::VARCHAR,
                    ({_entity_name(s)})::VARCHAR,
                    unnest(ST_Dump(geometry)).geom AS geom
                FROM read_parquet('{prepare_dir / polygons}.parquet'))"""
            for s, polygons in POLYGONS.items()
        ],
    )
    logger.info("polygon parts: %.0fs", perf_counter() - start)
    _step(
        conn,
        "polygon areas",
        """CREATE OR REPLACE TABLE polygon_areas AS
        SELECT source, code, name, sum(ST_Area_Spheroid(geom)) AS m2
        FROM polygon_parts GROUP BY ALL""",
    )


def _assign(conn: DuckDBPyConnection) -> None:
    """Clip land chunks to every source's cells and put each island in one cell."""
    cells = " UNION ALL ".join(
        f"""SELECT '{s}' AS source, coalesce(({c["id"]})::VARCHAR, '') AS entity,
            ({c["code"]})::VARCHAR AS code,
            ({_entity_name(s)})::VARCHAR AS name, geometry AS geom
        FROM read_parquet('{prepare_dir / VORONOI[s]}.parquet')"""
        for s, c in ((s, SOURCE_COLUMNS[s]) for s in sorted(VORONOI))
    )
    _chunks(conn, "cells", "cells", cells)
    conn.execute("""--sql
        CREATE OR REPLACE TABLE entities AS
        SELECT DISTINCT source, entity, code, name FROM cells
    """)
    # A chunk inside a cell stays as it is, which spares every overlay it enters.
    _step(
        conn,
        "pieces",
        f"""CREATE OR REPLACE TABLE pieces AS
        SELECT source, chunk, entity, whole, geom, CASE WHEN whole THEN chunk_km2
                ELSE {KM2.format("geom")} END AS km2,
            ST_XMin(geom) AS x0, ST_YMin(geom) AS y0,
            ST_XMax(geom) AS x1, ST_YMax(geom) AS y1
        FROM (
            SELECT *, CASE WHEN whole THEN chunk_geom ELSE ST_CollectionExtract(
                    ST_Intersection(chunk_geom, cell_geom), 3) END AS geom
            FROM (
                SELECT c.source, k.chunk, c.entity, k.km2 AS chunk_km2,
                    k.geom AS chunk_geom, c.geom AS cell_geom,
                    ST_Covers(c.geom, k.geom) AS whole
                FROM chunks k JOIN cells c
                  ON ST_Intersects(k.env, c.env) AND ST_Intersects(k.geom, c.geom)))
        """,
    )
    _polygons(conn)
    _step(
        conn,
        "islands placed",
        """CREATE OR REPLACE TABLE placed AS
        SELECT c.source, i.fid, min(c.entity) AS entity
        FROM islands i JOIN cells c ON ST_Intersects(i.pt, c.geom)
        GROUP BY c.source, i.fid""",
    )


def _overlay(conn: DuckDBPyConnection) -> None:
    """Overlay every source pair's pieces and islands, then mutual best matches."""
    # Pieces of one chunk overlap only if their boxes do, and a whole piece cuts
    # nothing, so two whole pieces just name their chunk.
    _step(
        conn,
        "overlay",
        f"""CREATE OR REPLACE TABLE overlay AS
        SELECT a, b, a_entity, b_entity, chunk,
            coalesce(known, {KM2.format("geom")}) AS km2, geom
        FROM (
            SELECT pa.source AS a, pb.source AS b, pa.entity AS a_entity,
                pb.entity AS b_entity, pa.chunk,
                CASE WHEN pa.whole THEN pb.km2 WHEN pb.whole THEN pa.km2 END AS known,
                CASE WHEN pa.whole AND pb.whole THEN NULL
                    WHEN pa.whole THEN pb.geom WHEN pb.whole THEN pa.geom
                    ELSE ST_CollectionExtract(ST_Intersection(pa.geom, pb.geom), 3)
                    END AS geom
            FROM pieces pa JOIN pieces pb ON pa.chunk = pb.chunk
                AND pa.source < pb.source AND pa.x0 <= pb.x1 AND pb.x0 <= pa.x1
                AND pa.y0 <= pb.y1 AND pb.y0 <= pa.y1)
        WHERE geom IS NULL OR NOT ST_IsEmpty(geom)""",
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
        WITH codes AS (
            SELECT source, entity, upper(code) AS code FROM entities
            WHERE coalesce(code, '') <> ''
            QUALIFY count(*) OVER (PARTITION BY source, upper(code)) = 1)
        -- A code held by one entity in each source pairs them, whatever the overlap.
        SELECT w.*, coalesce(ca.code = cb.code, false)
            OR (km2 = max(km2) OVER (PARTITION BY a, b, a_entity)
                AND km2 = max(km2) OVER (PARTITION BY a, b, b_entity)) AS mutual
        FROM weights w
        LEFT JOIN codes ca ON ca.source = w.a AND ca.entity = w.a_entity
        LEFT JOIN codes cb ON cb.source = w.b AND cb.entity = w.b_entity;
    """)
    _land_patches(conn)
    _parts(conn)


def _named(side: str) -> str:
    return f"""LEFT JOIN entities {side}e
        ON {side}e.source = d.{side} AND {side}e.entity = d.{side}_entity"""


PAIR_COLUMNS = """d.a || '|' || d.b AS pair, d.a, d.b, d.a_entity, ae.code AS a_code,
    ae.name AS a_name, d.b_entity, be.code AS b_code, be.name AS b_name"""
# A patch shows in the source whose entity has no mutual match in the other.
SIDE = """CASE WHEN pa.entity IS NULL AND pb.entity IS NOT NULL THEN 'a'
    WHEN pb.entity IS NULL AND pa.entity IS NOT NULL THEN 'b' ELSE 'both' END"""


def _sided() -> str:
    return " ".join(
        f"""LEFT JOIN paired p{x} ON p{x}.a = d.a AND p{x}.b = d.b
            AND p{x}.side = '{x}' AND p{x}.entity = d.{x}_entity"""
        for x in "ab"
    )


def _parts(conn: DuckDBPyConnection) -> None:
    """Each source's polygon parts off crossed land, placed in every source's cells."""
    bbox = getenv("DIFF_BBOX")
    within = f"WHERE ST_Intersects(env, ST_MakeEnvelope({bbox}))" if bbox else ""
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE parts AS
        SELECT row_number() OVER () AS pid, source, entity, geom, env
        FROM polygon_parts {within}
    """)
    # Only parts whose box meets crossed land need subdividing to test them.
    _step(
        conn,
        "near parts",
        """CREATE OR REPLACE TABLE near_parts AS
        SELECT DISTINCT p.pid FROM parts p JOIN chunks c
            ON ST_Intersects(p.env, c.env)""",
    )
    _chunks(
        conn,
        "part chunks",
        "part_bits",
        "SELECT pid, geom FROM parts WHERE pid IN (SELECT pid FROM near_parts)",
    )
    _step(
        conn,
        "island parts",
        f"""CREATE OR REPLACE TABLE part_land AS
        SELECT DISTINCT b.pid FROM part_bits b JOIN chunks c
            ON ST_Intersects(b.env, c.env) AND ST_Intersects(b.geom, c.geom);
        CREATE OR REPLACE TABLE island_parts AS
        SELECT pid, source, entity, {KM2.format("geom")} AS km2,
            ST_PointOnSurface(geom) AS pt, geom, env
        FROM parts WHERE pid NOT IN (SELECT pid FROM part_land);
        DROP TABLE part_bits; DROP TABLE parts""",
    )
    _step(
        conn,
        "parts placed",
        """CREATE OR REPLACE TABLE part_cells AS
        SELECT c.source, p.pid, min(c.entity) AS entity
        FROM island_parts p JOIN cells c ON ST_Intersects(p.pt, c.geom)
        GROUP BY c.source, p.pid""",
    )
    # A part's own source holds it by its polygon, whatever its cell says.
    conn.execute("""--sql
        CREATE OR REPLACE TABLE part_placed AS
        SELECT c.* FROM part_cells c JOIN island_parts p USING (pid)
        WHERE c.source <> p.source
        UNION ALL SELECT source, pid, entity FROM island_parts;
        DROP TABLE part_cells
    """)


def _patches(conn: DuckDBPyConnection) -> None:
    """Unshared land per pair, and each source's islands another's cells reassign."""
    conn.execute("""--sql
        CREATE OR REPLACE TABLE patches AS
        SELECT pair, 'land' AS type, side, item, a_entity, b_entity, a_code, a_name,
                b_code, b_name, km2, geom::GEOMETRY AS geometry
        FROM land_review
        UNION ALL
        SELECT d.a || '|' || d.b, 'island', d.side, d.item, d.a_entity, d.b_entity,
               ae.code, ae.name, be.code, be.name, d.km2, d.geom::GEOMETRY
        FROM (
            SELECT least(p.source, o.source) AS a, greatest(p.source, o.source) AS b,
                CASE WHEN p.source < o.source THEN 'a' ELSE 'b' END AS side,
                CASE WHEN p.source < o.source THEN p.entity ELSE o.entity END
                    AS a_entity,
                CASE WHEN p.source < o.source THEN o.entity ELSE p.entity END
                    AS b_entity,
                r.item, p.km2, p.geom
            FROM item_parts r JOIN island_parts p USING (pid)
            JOIN part_placed o ON o.pid = p.pid AND o.source <> p.source
            JOIN clusters cp ON cp.source = p.source AND cp.entity = p.entity
            JOIN clusters co ON co.source = o.source AND co.entity = o.entity
            WHERE cp.cluster <> co.cluster) d
        LEFT JOIN entities ae ON ae.source = d.a AND ae.entity = d.a_entity
        LEFT JOIN entities be ON be.source = d.b AND be.entity = d.b_entity
    """)


def _drop_crowded(conn: DuckDBPyConnection, table: str, group: str, size: str) -> None:
    """Delete each part of `table` within REACH widths of a larger part of its group."""
    # Groups sit side by side on x offsets, so the R-tree join never pairs two groups.
    conn.execute(f"""--sql
        CREATE OR REPLACE TEMP TABLE boxes AS
        SELECT id, {size} AS size, (x0 + x1) / 2 AS cx, (y0 + y1) / 2 AS cy,
            greatest(x1 - x0, y1 - y0) AS w, {REACH} * w AS reach,
            x0 - reach AS bx0, y0 - reach AS by0, x1 + reach AS bx1, y1 + reach AS by1,
            dense_rank() OVER (ORDER BY {group}) * (360 + 2 * max(reach) OVER ()) AS off
        FROM {table};
        DELETE FROM {table} WHERE id IN (
            WITH pairs AS MATERIALIZED (
                SELECT s.id AS sid, s.size AS ss, b.id AS bid, b.size AS bs
                FROM boxes s JOIN boxes b ON ST_Intersects(
                    ST_MakeEnvelope(b.off + b.bx0, b.by0, b.off + b.bx1, b.by1),
                    ST_Point(s.off + s.cx, s.cy)))
            SELECT sid FROM pairs WHERE bs > ss OR (bs = ss AND bid < sid));
        DROP TABLE boxes
    """)


def _dots(conn: DuckDBPyConnection) -> None:
    """Dot each island that is not crowded by a larger one in its item."""
    conn.execute("""--sql
        CREATE TEMP TABLE dot_islands AS
        SELECT row_number() OVER () AS id, pair, side, item, km2, geometry,
            ST_XMin(geometry) AS x0, ST_XMax(geometry) AS x1,
            ST_YMin(geometry) AS y0, ST_YMax(geometry) AS y1
        FROM patches WHERE type = 'island'
    """)
    _drop_crowded(conn, "dot_islands", "pair, side, item", "km2")
    write_parquet(
        conn,
        """SELECT pair, side, item,
            ST_MaximumInscribedCircle(geometry).center AS geometry
        FROM dot_islands""",
        prepare_dir / "differences_dots.parquet",
    )


def _areas(conn: DuckDBPyConnection) -> None:
    """Voronoi areas a pair assigns differently, each with its largest patch's item."""
    conn.execute("""--sql
        CREATE OR REPLACE TABLE targets AS
        SELECT DISTINCT pair, split_part(pair, '|', 1) AS a,
            split_part(pair, '|', 2) AS b, a_entity, b_entity
        FROM patches WHERE NOT (type = 'land' AND side = 'both')
            AND a_entity IS NOT NULL AND b_entity IS NOT NULL
    """)
    _step(
        conn,
        "area overlay",
        """CREATE OR REPLACE TABLE area_parts AS
        SELECT row_number() OVER () AS id, pair, a_entity, b_entity, geom FROM (
            SELECT pair, a_entity, b_entity, unnest(ST_Dump(g)).geom AS geom FROM (
                SELECT t.pair, t.a_entity, t.b_entity, ST_Union_Agg(
                    ST_CollectionExtract(ST_Intersection(ca.geom, cb.geom), 3)) AS g
                FROM targets t
                JOIN cells ca ON ca.source = t.a AND ca.entity = t.a_entity
                JOIN cells cb ON cb.source = t.b AND cb.entity = t.b_entity
                    AND ST_Intersects(ca.env, cb.env)
                    AND ST_Intersects(ca.geom, cb.geom)
                GROUP BY ALL))""",
    )
    _step(
        conn,
        "area items",
        f"""CREATE OR REPLACE TABLE areas AS
        SELECT any_value(v.pair) AS pair, 'voronoi' AS type,
            arg_max(p.side, p.km2) AS side, arg_max(p.item, p.km2) AS item,
            arg_max(p.a_code, p.km2) AS a_code, arg_max(p.a_name, p.km2) AS a_name,
            arg_max(p.b_code, p.km2) AS b_code, arg_max(p.b_name, p.km2) AS b_name,
            {KM2.format("any_value(v.geom)")} AS km2, any_value(v.geom) AS geometry
        FROM area_parts v JOIN patches p ON p.pair = v.pair
            AND p.a_entity = v.a_entity AND p.b_entity = v.b_entity
            AND NOT (p.type = 'land' AND p.side = 'both')
            AND ST_Intersects(v.geom, p.geometry)
        GROUP BY v.id""",
    )


def _land_patches(conn: DuckDBPyConnection) -> None:
    """Split the land each pair's entities don't share into patches."""
    conn.execute("""--sql
        CREATE OR REPLACE TABLE paired AS
        SELECT DISTINCT a, b, 'a' AS side, a_entity AS entity FROM matches WHERE mutual
        UNION SELECT DISTINCT a, b, 'b', b_entity FROM matches WHERE mutual
    """)
    _step(
        conn,
        "land patches",
        f"""CREATE OR REPLACE TABLE land_diff AS
        SELECT {PAIR_COLUMNS}, {SIDE} AS side, {KM2.format("geom")} AS km2, geom FROM (
            SELECT a, b, a_entity, b_entity, unnest(ST_Dump(g)).geom AS geom FROM (
                SELECT a, b, a_entity, b_entity,
                    ST_Union_Agg(coalesce(o.geom, k.geom)) AS g
                FROM overlay o JOIN matches m USING (a, b, a_entity, b_entity)
                LEFT JOIN chunks k USING (chunk)
                WHERE NOT m.mutual GROUP BY ALL)) d {_named("a")} {_named("b")}
        {_sided()}""",
    )


def _write(conn: DuckDBPyConnection) -> None:
    register_dir.mkdir(parents=True, exist_ok=True)
    write_parquet(
        conn,
        f"""SELECT {PAIR_COLUMNS}, d.km2, d.mutual
        FROM matches d {_named("a")} {_named("b")}""",
        register_dir / "matches.parquet",
        geo=False,
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
        f"""SELECT i.fid, i.km2, {entity}
        FROM islands i JOIN placed p USING (fid)
        LEFT JOIN entities e USING (source, entity)
        GROUP BY i.fid, i.km2 ORDER BY i.km2 DESC""",
        register_dir / "islands.parquet",
        geo=False,
    )
    write_parquet(
        conn,
        f"""SELECT r.pid, any_value(r.drawn) AS drawn, any_value(i.km2) AS km2,
            {entity}, any_value(r.item) AS item, any_value(i.geom) AS geometry
        FROM item_parts r JOIN island_parts i USING (pid)
        JOIN part_placed p USING (pid)
        LEFT JOIN entities e ON e.source = p.source AND e.entity = p.entity
        GROUP BY r.pid ORDER BY km2 DESC""",
        register_dir / "island_parts.parquet",
    )
    _patches(conn)
    _dots(conn)
    _areas(conn)
    write_parquet(
        conn,
        """SELECT * EXCLUDE (a_entity, b_entity) FROM patches
        UNION ALL BY NAME SELECT * FROM areas""",
        prepare_dir / "differences.parquet",
    )
    _items(conn)


def _items(conn: DuckDBPyConnection) -> None:
    """Write items.json, titling each item with its smallest entity's own name."""
    named = " UNION ALL ".join(
        f"SELECT item, '{s}' AS source, {s}_code AS code, {s}_name AS name FROM items"
        for s in sorted(VORONOI)
    )
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE titles AS
        SELECT n.item, arg_min(n.name, a.m2) AS title
        FROM ({named}) n JOIN polygon_areas a USING (source, code, name)
        GROUP BY n.item
    """)
    cols = ", ".join(
        f"{s}_code AS code_{s}, {s}_name AS name_{s}" for s in sorted(VORONOI)
    )
    lost = conn.execute("""--sql
        SELECT count(*) FROM (
            SELECT item FROM patches WHERE NOT (type = 'land' AND side = 'both')
            UNION ALL SELECT item FROM areas)
        WHERE item IS NULL OR item NOT IN (SELECT item FROM items)""").fetchall()[0][0]
    if lost:
        msg = f"{lost} differences belong to no item"
        raise ValueError(msg)
    out = tiles_dir / "items.json"
    conn.execute(f"""--sql
        COPY (SELECT item, t.title, type, drawn, same_code, missing, s.islands, s.km2,
                [s.xmin, s.ymin, s.xmax, s.ymax] AS bbox,
                (SELECT list(DISTINCT pair ORDER BY pair) FROM patches p
                 WHERE p.item = i.item
                    AND NOT (p.type = 'land' AND p.side = 'both')) AS pairs,
                {cols}
            FROM items i LEFT JOIN stats s USING (item)
            LEFT JOIN titles t USING (item)
            WHERE type <> 'island' OR item IN (SELECT item FROM patches)
            ORDER BY type, s.km2 DESC) TO '{out}' (FORMAT JSON, ARRAY true)
    """)


REGISTER = ("matches", "land", "islands", "island_parts", "items", "borders")
# Each phase reads the tables the phases before it left in the database.
PHASES = {"land": _land, "assign": _assign, "overlay": _overlay, "review": _write}


def main() -> None:
    """Write land and island differences for every source pair."""
    parser = ArgumentParser()
    parser.add_argument("--from", dest="start", choices=PHASES, default="land")
    args, _ = parser.parse_known_args()
    code = [Path(__file__), Path(review.__file__)]
    layer_ids = [*VORONOI.values(), *POLYGONS.values(), *LINES, "osm_land"]
    inputs = code + [prepare_dir / f"{name}.parquet" for name in layer_ids]
    outputs = [
        tiles_dir / "items.json",
        prepare_dir / "differences.parquet",
        prepare_dir / "differences_dots.parquet",
        *(register_dir / f"{name}.parquet" for name in REGISTER),
    ]
    names = list(PHASES)
    complete = args.start == names[0] and not getenv("DIFF_BBOX")
    if complete and fresh("differences", inputs, outputs):
        logger.info("differences: unchanged")
        return
    conn = open_db(tmp_dir / "differences.duckdb", keep=args.start != names[0])
    conn.execute("""--sql
        SET GLOBAL geometry_always_xy = true;
        SET GLOBAL preserve_insertion_order = false
    """)
    for name in names[names.index(args.start) :]:
        PHASES[name](conn)
    conn.close()
    # A partial run leaves the next plain run nothing to skip.
    record("differences", inputs if complete else [])
