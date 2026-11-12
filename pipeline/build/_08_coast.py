"""Clip OSM land to the extended units, and list what the new coastline changes."""

import json
from logging import getLogger
from os import getenv
from pathlib import Path
from typing import TYPE_CHECKING

from pipeline.config import file_hash, prepare_dir, root, tmp_dir, write_parquet
from pipeline.differences import SLICES, _chunks, _parallel, _step

from . import _06_export as export
from .common import (
    KM2,
    changes,
    connect,
    curated_dir,
    data,
    finish,
    manifest_path,
    names,
    stage_dir,
    unchanged,
)

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

logger = getLogger(__name__)

BBOX = getenv("COAST_BBOX")
OVERRIDES = curated_dir / "coast_overrides.csv"
DECISIONS = curated_dir / "review_decisions.csv"
WP = prepare_dir / "wp_polygons.parquet"
PARTIES = curated_dir / "dispute_parties.csv"
GRID = 1e-9
# UN Geodata's status for its disputed areas, given to entities the overrides add.
DISPUTED = (99, "Undetermined")
TOLERANCE_KM2 = 0.01
TOLERANCE_DEG2 = 1e-6
OVERLAP_SHARE = 1e-5


def _out(name: str) -> Path:
    """Return an output path, in a scratch folder when ``COAST_BBOX`` is set."""
    folder = tmp_dir / "coast_bbox" if BBOX else stage_dir("08")
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name


def _clipped(path: str, columns: str) -> str:
    """Select ``columns`` and polygons as ``geom``, clipped to ``COAST_BBOX``."""
    if not BBOX:
        return f"SELECT {columns}, geometry AS geom FROM '{path}'"
    box = f"ST_MakeEnvelope({BBOX})"
    return f"""--sql
        SELECT {columns}, ST_CollectionExtract(ST_Intersection(geometry, {box}), 3)
            AS geom
        FROM '{path}' WHERE ST_Intersects(geometry, {box})"""


def _load(conn: DuckDBPyConnection) -> None:
    """Chunk OSM land, the units' parts, the units' cells and FieldMaps' cells."""
    _step(
        conn,
        "land",
        f"""CREATE TABLE land AS SELECT fid, geom, {KM2.format("geom")} AS km2
        FROM ({_clipped(data("01", "osm_land"), "fid")}) WHERE NOT ST_IsEmpty(geom)""",
    )
    _chunks(conn, "land chunks", "chunks", "SELECT fid, geom FROM land")
    conn.execute("""--sql
        CREATE OR REPLACE TABLE chunks AS
        SELECT row_number() OVER () AS chunk, * FROM chunks
    """)
    parts = f"""--sql
        SELECT unit_id, d.path[1] AS part_no, d.geom FROM (
            SELECT unit_id, unnest(ST_Dump(geom)) AS d
            FROM ({_clipped(data("05", "units"), "unit_id")}))"""
    _chunks(conn, "unit bits", "bits", parts)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE bits AS
        SELECT row_number() OVER () AS bit, *, {KM2.format("geom")} AS km2 FROM bits
    """)
    _chunks(
        conn,
        "cells",
        "cells",
        _clipped(data("07", "units_voronoi"), "unit_id"),
    )
    _chunks(
        conn,
        "fieldmaps cells",
        "fm_cells",
        _clipped(
            data("01", "fieldmaps_voronoi"),
            "iso_3 AS fm_code, adm0_name1 AS fm_name",
        ),
    )


def _place(conn: DuckDBPyConnection) -> None:
    """Give each OSM polygon to units: whole by its UN land, or clipped by cells."""
    _step(
        conn,
        "touch",
        """CREATE TABLE touch_all AS
        SELECT k.chunk, k.fid, b.bit, b.unit_id, b.part_no,
               CASE WHEN ST_Covers(b.geom, k.geom) THEN k.geom
                    WHEN ST_Covers(k.geom, b.geom) THEN b.geom
                    ELSE ST_CollectionExtract(ST_Intersection(k.geom, b.geom), 3)
                    END AS geom
        FROM chunks k JOIN bits b
          ON ST_Intersects(k.env, b.env) AND ST_Intersects(k.geom, b.geom)""",
    )
    conn.execute(f"""--sql
        CREATE TABLE touch AS
        SELECT *, {KM2.format("geom")} AS km2 FROM touch_all
        WHERE NOT ST_IsEmpty(geom);
        DROP TABLE touch_all;
        CREATE TABLE fclass AS
        SELECT l.fid, count(DISTINCT t.unit_id) AS n, min(t.unit_id) AS only_unit
        FROM land l LEFT JOIN touch t USING (fid) GROUP BY l.fid;
        CREATE TABLE todo AS
        SELECT k.* FROM chunks k JOIN fclass f USING (fid) WHERE f.n >= 2;
        CREATE TABLE decisions AS
        SELECT upper(un) AS un, upper(fieldmaps) AS fm FROM read_csv('{DECISIONS}')
        WHERE action = 'remove';
        CREATE TABLE unit_codes AS
        SELECT u.unit_id, upper(coalesce(u.iso3, u.entity, n.iso3cd)) AS code
        FROM '{data("05", "units")}' u
        LEFT JOIN '{data("01", "un_polygons")}' n ON n.objectid = u.un_owner;
    """)
    _step(
        conn,
        "fieldmaps pieces",
        """CREATE TABLE fm_share AS
        SELECT k.fid, upper(c.fm_code) AS fm_code,
               sum(ST_Area(CASE WHEN ST_Covers(c.geom, k.geom) THEN k.geom
                   ELSE ST_Intersection(k.geom, c.geom) END)) AS area
        FROM chunks k JOIN fm_cells c
          ON ST_Intersects(k.env, c.env) AND ST_Intersects(k.geom, c.geom)
        WHERE k.fid IN (SELECT fid FROM fclass WHERE n = 0)
        GROUP BY ALL""",
    )
    _step(
        conn,
        "cell pieces",
        """CREATE TABLE placed_all AS
        SELECT k.chunk, k.fid, c.unit_id, ST_Covers(c.geom, k.geom) AS whole,
               CASE WHEN ST_Covers(c.geom, k.geom) THEN k.geom
                    ELSE ST_CollectionExtract(ST_Intersection(k.geom, c.geom), 3)
                    END AS geom
        FROM todo k JOIN cells c
          ON ST_Intersects(k.env, c.env) AND ST_Intersects(k.geom, c.geom)""",
    )
    overrides = f"""SELECT * FROM read_csv('{OVERRIDES}', header = true,
        columns = {{'lon': 'DOUBLE', 'lat': 'DOUBLE', 'unit_id': 'VARCHAR',
                   'name': 'VARCHAR', 'change_id': 'VARCHAR', 'reason': 'VARCHAR'}})"""
    conn.execute(f"""--sql
        CREATE TABLE placed AS
        SELECT p.*, f.n FROM placed_all p JOIN fclass f USING (fid)
        WHERE NOT ST_IsEmpty(p.geom);
        DROP TABLE placed_all;
        CREATE TABLE new_pts AS
        SELECT fid, ST_PointOnSurface(geom) AS pt FROM land
        WHERE fid IN (SELECT fid FROM fclass WHERE n = 0);
        CREATE TABLE cell_owner AS
        SELECT p.fid, min(c.unit_id) AS unit_id
        FROM new_pts p JOIN cells c ON ST_Intersects(p.pt, c.geom) GROUP BY p.fid;
        CREATE TABLE fm_owner AS
        SELECT fid, arg_max(fm_code, area) AS fm_code, count(*) > 1 AS straddle
        FROM fm_share GROUP BY fid;
        CREATE TABLE fm_moves AS
        SELECT w.fid, f.fm_code FROM cell_owner w JOIN fm_owner f USING (fid)
        JOIN unit_codes u USING (unit_id)
        WHERE f.fm_code <> u.code
          AND (u.code, f.fm_code) NOT IN (SELECT * FROM decisions);
        CREATE TABLE fm_target AS
        SELECT m.fid, arg_min(b.unit_id, ST_Distance(p.pt, b.geom)) AS unit_id
        FROM fm_moves m JOIN new_pts p USING (fid)
        JOIN unit_codes u ON u.code = m.fm_code JOIN bits b USING (unit_id)
        GROUP BY m.fid;
        CREATE TABLE new_owner AS
        SELECT w.fid, coalesce(t.unit_id, m.fm_code, w.unit_id) AS unit_id
        FROM cell_owner w LEFT JOIN fm_moves m USING (fid)
        LEFT JOIN fm_target t USING (fid);
        CREATE TABLE override_rows AS {overrides};
        CREATE TABLE overrides AS
        SELECT l.fid, o.unit_id, o.change_id
        FROM override_rows o
        JOIN land l ON ST_Intersects(l.geom, ST_Point(o.lon, o.lat));
        CREATE TABLE all_units AS
        SELECT * FROM '{data("05", "units")}'
        UNION ALL BY NAME
        SELECT unit_id, unit_id AS entity, any_value(change_id) AS change_ids
        FROM override_rows WHERE unit_id <> 'drop'
          AND unit_id NOT IN (SELECT unit_id FROM '{data("05", "units")}')
        GROUP BY unit_id
        UNION ALL BY NAME
        SELECT DISTINCT unit_id, unit_id AS entity FROM new_owner
        WHERE unit_id NOT IN (SELECT unit_id FROM '{data("05", "units")}')
          AND unit_id NOT IN (SELECT unit_id FROM override_rows);
        CREATE TABLE whole AS
        SELECT f.fid, f.n, coalesce(o.unit_id,
                   CASE WHEN f.n = 1 THEN f.only_unit ELSE w.unit_id END) AS unit_id,
               o.change_id AS override_change
        FROM fclass f LEFT JOIN new_owner w USING (fid)
        LEFT JOIN overrides o USING (fid)
        WHERE f.n <= 1;
        CREATE TABLE shared_groups AS
        SELECT DISTINCT unit_id, fid, hash(unit_id, fid) % {SLICES} AS slice
        FROM placed WHERE n >= 2;
        CREATE TABLE shared_union (unit_id VARCHAR, fid BIGINT, geom GEOMETRY);
    """)
    _parallel(
        conn,
        [
            f"""INSERT INTO shared_union
            SELECT p.unit_id, p.fid, ST_Union_Agg(p.geom)
            FROM placed p JOIN shared_groups g USING (unit_id, fid)
            WHERE g.slice = {i} GROUP BY p.unit_id, p.fid"""
            for i in range(SLICES)
        ],
    )
    n = conn.execute("""--sql
        SELECT count(*) FILTER (n = 0), count(*) FILTER (n = 1),
               count(*) FILTER (n >= 2) FROM fclass""").fetchall()[0]
    logger.info("land: %d new, %d single-unit, %d shared polygons", *n)


def _coast_units(conn: DuckDBPyConnection) -> None:
    """Write ``coast_units``: each unit's keys on its OSM land."""
    conn.execute(f"""--sql
        CREATE TABLE unit_land AS
        SELECT unit_id, geom, hash(unit_id) % {SLICES} AS slice
        FROM (SELECT w.unit_id, l.geom FROM whole w JOIN land l USING (fid)
              WHERE w.unit_id <> 'drop'
              UNION ALL SELECT unit_id, geom FROM shared_union);
        CREATE TABLE coast_geoms (unit_id VARCHAR, geometry GEOMETRY);
    """)
    # A union, as FieldMaps does: OSM land has small polygons on top of larger ones.
    _parallel(
        conn,
        [
            f"""INSERT INTO coast_geoms
            SELECT unit_id, ST_Multi(ST_CollectionExtract(ST_Union_Agg(geom), 3))
            FROM unit_land WHERE slice = {i} GROUP BY unit_id"""
            for i in range(SLICES)
        ],
    )
    conn.execute("""--sql
        CREATE TABLE coast_units AS
        SELECT u.* EXCLUDE geometry, g.geometry
        FROM all_units u JOIN coast_geoms g USING (unit_id);
    """)
    write_parquet(conn, "FROM coast_units", _out("coast_units.parquet"))


def _codes(conn: DuckDBPyConnection) -> None:
    """Name each unit by its entity in the UN export."""
    rows = [(e["code"], e["name"]) for c in changes() if (e := c.get("entity"))]
    conn.execute("CREATE TABLE new_entities (code VARCHAR, name VARCHAR)")
    conn.executemany("INSERT INTO new_entities VALUES (?, ?)", rows)
    conn.execute(f"""--sql
        INSERT INTO new_entities
        SELECT DISTINCT o.unit_id, o.name FROM override_rows o
        JOIN all_units u USING (unit_id) WHERE u.un_objectid IS NULL;
        INSERT INTO new_entities
        SELECT u.unit_id, f.name
        FROM all_units u JOIN ({names()}) f ON f.code = u.unit_id
        WHERE u.un_objectid IS NULL
          AND u.unit_id NOT IN (SELECT code FROM new_entities);
        CREATE TABLE codes AS
        SELECT u.unit_id, coalesce(u.entity, n.iso3cd) AS code,
               coalesce(f.name, e.name, n.romnam, n.iso3cd) AS name
        FROM all_units u
        LEFT JOIN '{data("01", "un_polygons")}' n ON n.objectid = u.un_owner
        LEFT JOIN (SELECT DISTINCT code, name FROM new_entities) e
          ON e.code = u.entity
        LEFT JOIN ({names()}) f ON f.code = coalesce(u.entity, n.iso3cd);
    """)


def _patches(conn: DuckDBPyConnection) -> None:
    """Write land gained and lost along the coast, new islands and dropped parts."""
    # Overlay on a 1e-9° grid: unsnapped, some pieces inside the land came out whole.
    _step(
        conn,
        "patches",
        f"""--sql
        CREATE TABLE un_in_chunk AS
        SELECT chunk, ST_ReducePrecision(ST_Union_Agg(geom), {GRID}) AS geom
        FROM touch GROUP BY chunk;
        CREATE TABLE land_in_bit AS
        SELECT bit, ST_ReducePrecision(ST_Union_Agg(geom), {GRID}) AS geom
        FROM touch GROUP BY bit;
        CREATE TABLE owned AS
        SELECT k.chunk, k.fid, f.only_unit AS unit_id, k.geom
        FROM chunks k JOIN fclass f USING (fid) WHERE f.n = 1
        UNION ALL SELECT chunk, fid, unit_id, geom FROM placed WHERE n >= 2;
        CREATE TABLE gained_raw AS
        SELECT o.unit_id, o.fid, CASE WHEN u.geom IS NULL THEN o.geom
                   ELSE ST_CollectionExtract(
                       ST_Difference(ST_ReducePrecision(o.geom, {GRID}), u.geom), 3)
                   END AS geom
        FROM owned o LEFT JOIN un_in_chunk u USING (chunk);
        CREATE TABLE lost_raw AS
        SELECT b.unit_id, b.part_no, CASE WHEN l.geom IS NULL THEN b.geom
                   ELSE ST_CollectionExtract(
                       ST_Difference(ST_ReducePrecision(b.geom, {GRID}), l.geom), 3)
                   END AS geom
        FROM bits b LEFT JOIN land_in_bit l USING (bit);
        """,
    )
    # Chunks of one OSM polygon or UN part are rejoined, so a patch is never split.
    rejoin = """SELECT unit_id, {key}, unnest(ST_Dump(geom)).geom AS geom FROM (
            SELECT unit_id, {key}, geom FROM pieces WHERE n = 1
            UNION ALL SELECT unit_id, {key}, ST_Union_Agg(geom) FROM pieces
            WHERE n > 1 GROUP BY unit_id, {key})"""
    pieces = """WITH pieces AS (
            SELECT *, count(*) OVER (PARTITION BY unit_id, {key}) AS n FROM (
                SELECT unit_id, {key}, unnest(ST_Dump(geom)).geom AS geom FROM {raw}
                WHERE NOT ST_IsEmpty(geom)))"""
    _step(
        conn,
        "rejoin",
        f"""--sql
        CREATE TABLE gained_joined AS
        {pieces.format(key="fid", raw="gained_raw")} {rejoin.format(key="fid")};
        CREATE TABLE lost_joined AS
        {pieces.format(key="part_no", raw="lost_raw")} {rejoin.format(key="part_no")};
        """,
    )
    km2 = KM2.format("geom")
    conn.execute(f"""--sql
        CREATE TABLE gained AS
        SELECT unit_id, geom, {km2} AS km2, ST_PointOnSurface(geom) AS pt
        FROM gained_joined;
        CREATE TABLE lost AS
        SELECT unit_id, part_no, geom, {km2} AS km2 FROM lost_joined;
        CREATE TABLE gained_fm AS
        SELECT g.unit_id, g.km2, g.geom, min(c.fm_code) AS fm_code
        FROM gained g JOIN fm_cells c ON ST_Intersects(g.pt, c.geom)
        GROUP BY ALL;
        CREATE TABLE dropped AS
        SELECT b.unit_id, b.part_no, ST_Union_Agg(b.geom) AS geom, sum(b.km2) AS km2
        FROM bits b WHERE (b.unit_id, b.part_no) NOT IN (
            SELECT DISTINCT unit_id, part_no FROM touch)
        GROUP BY b.unit_id, b.part_no;
        CREATE TABLE new_islands AS
        SELECT w.fid, w.unit_id, w.override_change, l.km2, l.geom,
               coalesce(f.straddle, false) AS straddle, f.fm_code
        FROM whole w JOIN land l USING (fid) LEFT JOIN fm_owner f USING (fid)
        WHERE w.n = 0 AND w.unit_id IS NOT NULL AND w.unit_id <> 'drop';
        CREATE TABLE moved AS
        SELECT t.unit_id AS un_unit, p.unit_id AS to_unit,
               {KM2.format("ST_Intersection(p.geom, t.geom)")} AS km2
        FROM touch t JOIN placed p ON p.chunk = t.chunk AND p.unit_id <> t.unit_id
        WHERE ST_Intersects(p.geom, t.geom);
        CREATE TABLE foreign_pieces AS
        SELECT p.unit_id, p.fid, {KM2.format("p.geom")} AS km2, p.geom
        FROM placed p WHERE p.n >= 2 AND (p.fid, p.unit_id) NOT IN (
            SELECT DISTINCT fid, unit_id FROM touch);
    """)


def _parties(conn: DuckDBPyConnection) -> dict:
    """Return the parties to each new island entity, from WP or the curated list."""
    parties = dict(
        conn.execute(f"""--sql
        SELECT t.change_id, mode(string_split(w.Map_Disp, ','))
        FROM new_tagged t JOIN (
            SELECT Map_Disp, geometry FROM '{WP}' WHERE Map_Disp IS NOT NULL) w
          ON ST_DWithin(w.geometry, t.geom, 0.05)
        WHERE t.change_id = 'N-' || t.code GROUP BY 1
    """).fetchall()
    )
    for code, claims in conn.execute(f"FROM '{PARTIES}'").fetchall():
        parties.setdefault(f"N-{code}", claims.split(","))
    return parties


def _records(conn: DuckDBPyConnection) -> list[dict]:
    """Return one record per entity and kind of change, as in ``changes.json``."""
    conn.execute(f"""--sql
        CREATE TABLE new_tagged AS
        SELECT i.*, c.code, c.name,
               CASE WHEN i.override_change IS NOT NULL THEN i.override_change
                    WHEN i.unit_id NOT IN (SELECT unit_id FROM '{data("05", "units")}')
                    THEN 'N-' || c.code
                    ELSE 'K-' || c.code END AS change_id
        FROM new_islands i JOIN codes c USING (unit_id);
        CREATE TABLE gained_tagged AS
        SELECT g.*, c.code, 'K-' || c.code AS change_id,
               g.fm_code IS NOT NULL AND upper(g.fm_code) <> upper(c.code)
               AND (upper(c.code), upper(g.fm_code))
                   NOT IN (SELECT un, fm FROM decisions) AS fm_differs
        FROM gained_fm g JOIN codes c USING (unit_id);
        CREATE TABLE lost_tagged AS
        SELECT l.*, 'K-' || c.code AS change_id
        FROM lost l JOIN codes c USING (unit_id);
        CREATE TABLE dropped_tagged AS
        SELECT d.*, c.code, c.name, 'K-' || c.code AS change_id
        FROM dropped d JOIN codes c USING (unit_id);
    """)
    box = """[min(ST_XMin(geom)), min(ST_YMin(geom)),
              max(ST_XMax(geom)), max(ST_YMax(geom))]"""
    largest = """arg_max([ST_XMin(geom), ST_YMin(geom),
                          ST_XMax(geom), ST_YMax(geom)], km2)"""
    records = []

    def value(code: str, name: str, km2: float) -> dict:
        return {
            "un": code,
            "un_name": name,
            "gaul": code,
            "gaul_name": name,
            "km2": round(km2, 3),
        }

    coast = conn.execute(f"""--sql
        WITH un_area AS (SELECT unit_id, sum(km2) AS km2 FROM bits GROUP BY 1),
        kept AS (SELECT unit_id, sum(km2) AS km2 FROM touch GROUP BY 1),
        parts AS (
            SELECT code, 'gain' AS kind, km2, fm_differs, geom FROM gained_tagged
            UNION ALL SELECT c.code, 'loss', l.km2, false, l.geom
                FROM lost l JOIN codes c USING (unit_id)
            UNION ALL SELECT code, 'drop', km2, false, geom FROM dropped_tagged
            UNION ALL SELECT code, 'add', km2, false, geom FROM new_tagged
                WHERE change_id = 'K-' || code),
        agg AS (SELECT code,
                       coalesce(sum(km2) FILTER (kind = 'gain'), 0) AS gain,
                       coalesce(sum(km2) FILTER (kind = 'loss'), 0) AS loss,
                       coalesce(sum(km2) FILTER (kind = 'drop'), 0) AS drop,
                       coalesce(sum(km2) FILTER (kind = 'add'), 0) AS add,
                       count(*) FILTER (kind = 'add') AS islands,
                       sum(km2) FILTER (fm_differs) AS fm_km2,
                       {box} AS box, {largest} AS big, count(*) AS n
                FROM parts GROUP BY code)
        SELECT c.code, any_value(c.name), sum(u.km2), sum(coalesce(k.km2, 0)),
               any_value(a.gain), any_value(a.loss), any_value(a.drop),
               any_value(a.add), any_value(a.islands), any_value(a.fm_km2),
               any_value(a.box), any_value(a.big), any_value(a.n)
        FROM codes c JOIN un_area u USING (unit_id) LEFT JOIN kept k USING (unit_id)
        LEFT JOIN agg a ON a.code = c.code
        GROUP BY c.code ORDER BY c.code
    """).fetchall()
    for row in coast:
        code, name, un_km2, kept, gain, loss, drop, add, isles, fm_km2, *rest = row
        bbox, big, n = rest
        if not n:
            continue
        records.append(
            {
                "id": f"K-{code}",
                "type": "coast",
                "keys": [],
                "km2": round(gain + loss + drop + add, 3),
                "gained_km2": round(gain, 3),
                "lost_km2": round(loss, 3),
                "dropped_km2": round(drop, 3),
                "added_km2": round(add, 3),
                "islands": isles,
                "un_km2": round(un_km2, 3),
                "kept_km2": round(kept, 3),
                "fieldmaps_differs_km2": round(fm_km2 or 0, 3),
                "units": 0,
                "bbox": bbox,
                "largest_patch_bbox": big,
                "patches": n,
                "values": [value(code, name, gain + add - loss - drop)],
            }
        )
    islands = conn.execute(f"""--sql
        SELECT change_id, code, any_value(name), sum(km2), count(*),
               count(*) FILTER (straddle), {box}, {largest}
        FROM new_tagged WHERE change_id <> 'K-' || code
        GROUP BY change_id, code ORDER BY 4 DESC
    """).fetchall()
    parties = _parties(conn)
    for change_id, code, name, km2, n, straddles, bbox, big in islands:
        records.append(
            {
                "id": change_id,
                "type": "new_island",
                "parties": parties.get(change_id, []),
                "keys": [],
                "km2": round(km2, 3),
                "islands": n,
                "straddle": straddles,
                "units": 0,
                "bbox": bbox,
                "largest_patch_bbox": big,
                "patches": n,
                "values": [value(code, name, km2)],
                "review": False,
            }
        )
    return records


def _layers(conn: DuckDBPyConnection) -> None:
    """Write the patch layers the page draws over the units."""
    for name, query in {
        "gained": "SELECT change_id, km2, fm_code, fm_differs, geom AS geometry "
        "FROM gained_tagged",
        "lost": "SELECT change_id, km2, geom AS geometry FROM lost_tagged",
        "new_islands": "SELECT change_id, fid, km2, straddle, fm_code, "
        "geom AS geometry FROM new_tagged",
        "dropped": "SELECT change_id, km2, geom AS geometry FROM dropped_tagged",
    }.items():
        write_parquet(conn, query, _out(f"{name}.parquet"))


def _checks(conn: DuckDBPyConnection, un: Path, adm0: Path) -> dict:
    """Return each check's name, measured value and whether it passed."""

    def one(sql: str) -> object:
        return conn.execute(sql).fetchall()[0][0]

    # Planar area: spheroidal area of one polygon differs from its chunks' sum.
    land = one("SELECT sum(ST_Area(geom)) FROM land")
    coast = one("SELECT sum(ST_Area(geometry)) FROM coast_units")
    dropped = one("""--sql
        SELECT coalesce(sum(ST_Area(l.geom)), 0) FROM land l JOIN whole w USING (fid)
        WHERE w.unit_id = 'drop'""")
    added = one("SELECT count(*) FROM all_units WHERE un_objectid IS NULL")
    checks = {
        "land_unassigned": (
            n := one("SELECT count(*) FROM whole WHERE unit_id IS NULL"),
            n == 0,
        ),
        # What the union removes: OSM polygons lying on top of other OSM land.
        "osm_overlap_deg2": (
            d := land - dropped - coast,
            -TOLERANCE_DEG2 <= d <= land * OVERLAP_SHARE,
        ),
        "un_land_moved_km2": (
            d := one("SELECT coalesce(sum(km2), 0) FROM moved"),
            d <= TOLERANCE_KM2,
        ),
        "foreign_pieces_km2": (
            one("SELECT coalesce(sum(km2), 0) FROM foreign_pieces"),
            True,
        ),
        "coast_units_invalid": (
            n := one("SELECT count(*) FROM coast_units WHERE NOT ST_IsValid(geometry)"),
            n == 0,
        ),
    }
    if not BBOX:
        checks |= {
            "un_rows": (
                n := one(f"SELECT count(*) FROM '{un}'"),
                n == export.UN_ROWS + added,
            ),
            "adm0_rows": (
                n := one(f"SELECT count(*) FROM '{adm0}'"),
                n == one(f"SELECT count(*) FROM '{data('06', 'adm0')}'") + added,
            ),
        }
    return checks


def _cells_current() -> bool:
    """Return whether stage 07's cells were extended from the current units."""
    cells, units = Path(data("07", "units_voronoi")), Path(data("05", "units"))
    if not cells.exists() or not manifest_path.exists():
        return False
    record = json.loads(manifest_path.read_text()).get("stages", {}).get("07", {})
    return record.get("inputs", {}).get(str(units.relative_to(root))) == file_hash(
        units
    )


def main() -> None:
    """Write the units on OSM land, the ADM0 output, the patches and the changes."""
    if not _cells_current():
        logger.warning("stage 08: skipped, run --stage 07 for the current units")
        return
    inputs = [
        Path(__file__),
        Path(data("05", "units")),
        Path(data("07", "units_voronoi")),
        Path(data("01", "osm_land")),
        Path(data("01", "fieldmaps_voronoi")),
        Path(data("01", "un_polygons")),
        Path(data("01", "gaul_polygons")),
        Path(data("06", "adm0")),
        curated_dir / "changes.json",
        DECISIONS,
        OVERRIDES,
        WP,
        PARTIES,
    ]
    if not BBOX and all(unchanged("08", p) for p in inputs):
        logger.info("stage 08: inputs unchanged")
        return
    conn = connect()
    _load(conn)
    _place(conn)
    _coast_units(conn)
    _codes(conn)
    _patches(conn)
    records = _records(conn)
    out = _out("changes.json")
    out.write_text(json.dumps(records, ensure_ascii=False, indent=1) + "\n")
    _layers(conn)
    un, adm0 = _out("un.parquet"), _out("adm0.parquet")
    if not BBOX:
        added = conn.execute("""--sql
            SELECT DISTINCT e.code, e.name FROM new_entities e
            JOIN all_units u ON u.unit_id = e.code WHERE u.un_objectid IS NULL
        """).fetchall()
        export.exports(
            conn,
            str(_out("coast_units.parquet")),
            str(un),
            str(adm0),
            tuple((code, name, *DISPUTED) for code, name in added),
        )
    checks = _checks(conn, un, adm0)
    _out("checks.json").write_text(
        json.dumps(
            {k: {"value": v, "passed": p} for k, (v, p) in checks.items()}, indent=2
        )
        + "\n"
    )
    if not BBOX:
        finish(conn, "08", inputs)
    failed = [k for k, (_, passed) in checks.items() if not passed]
    if failed:
        msg = f"coast checks failed: {failed}"
        raise ValueError(msg)
