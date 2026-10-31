"""Build the GAUL-to-source overlap crosswalk under ``outputs/register/``."""

from logging import getLogger
from typing import TYPE_CHECKING

from .config import (
    BASELINE,
    SOURCE_COLUMNS,
    fieldmaps_dir,
    open_db,
    prepare_dir,
    register_dir,
    tmp_dir,
    write_parquet,
)

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

logger = getLogger(__name__)

# Each register source's polygons file, keyed as in SOURCE_COLUMNS.
SOURCES = {
    BASELINE: prepare_dir / "gaul_l0.parquet",
    "ungeodata": prepare_dir / "ungeodata_polygons.parquet",
    "fieldmaps": fieldmaps_dir / "polygons.parquet",
}


def _entities(conn: DuckDBPyConnection) -> None:
    """Load every source's entities into one long table with common columns."""
    conn.execute("""--sql
        CREATE OR REPLACE TABLE entities (
            source VARCHAR, id VARCHAR, code VARCHAR, sovereign VARCHAR,
            name VARCHAR, status VARCHAR, region VARCHAR, area DOUBLE,
            xmin DOUBLE, ymin DOUBLE, xmax DOUBLE, ymax DOUBLE, geom GEOMETRY
        )
    """)
    for source, path in SOURCES.items():
        if not path.exists():
            logger.warning("%s: %s missing, skipping", source, path.name)
            continue
        c = SOURCE_COLUMNS[source]
        sovereign = c.get("sovereign", "NULL")
        conn.execute(f"""--sql
            INSERT INTO entities
            SELECT '{source}', {c["id"]}, {c["code"]}, {sovereign},
                   {c.get("entity", c["name"])},
                   {c.get("status", "NULL")}, {c["region"]}, ST_Area(geometry),
                   ST_XMin(geometry), ST_YMin(geometry), ST_XMax(geometry),
                   ST_YMax(geometry), geometry
            FROM read_parquet('{path}')
        """)


def _crosswalk(conn: DuckDBPyConnection) -> None:
    """Overlap each GAUL entity with other sources' entities, one pair per call."""
    conn.execute("""--sql
        CREATE OR REPLACE TABLE crosswalk (
            gaul_id VARCHAR, source VARCHAR, other_id VARCHAR, overlap DOUBLE
        )
    """)
    pairs = conn.execute(f"""--sql
        SELECT g.id, o.source, o.id,
               greatest(g.xmin, o.xmin), greatest(g.ymin, o.ymin),
               least(g.xmax, o.xmax), least(g.ymax, o.ymax)
        FROM entities g JOIN entities o
          ON g.source = '{BASELINE}' AND o.source != '{BASELINE}'
         AND g.xmin <= o.xmax AND g.xmax >= o.xmin
         AND g.ymin <= o.ymax AND g.ymax >= o.ymin
        ORDER BY g.id
    """).fetchall()
    logger.info("crosswalk: %d candidate pairs", len(pairs))
    for i, (gid, source, oid, *box) in enumerate(pairs, 1):
        if i % 100 == 0:
            logger.info("crosswalk: %d/%d pairs", i, len(pairs))
        # Clipping both sides to the shared bbox first is exact and much cheaper.
        conn.execute(
            f"""--sql
            INSERT INTO crosswalk
            SELECT $1, $2, $3, ST_Area(ST_Intersection(
                ST_Intersection(g.geom, ST_MakeEnvelope($4, $5, $6, $7)),
                ST_Intersection(o.geom, ST_MakeEnvelope($4, $5, $6, $7))
            ))
            FROM entities g, entities o
            WHERE g.source = '{BASELINE}' AND g.id = $1 AND o.source = $2 AND o.id = $3
            """,
            [gid, source, oid, *box],
        )
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE crosswalk AS
        SELECT c.*, c.overlap / g.area AS gaul_share, c.overlap / o.area AS other_share
        FROM crosswalk c
        JOIN entities g ON g.source = '{BASELINE}' AND g.id = c.gaul_id
        JOIN entities o ON o.source = c.source AND o.id = c.other_id
        WHERE c.overlap > 0
    """)


def main() -> None:
    """Build and write the crosswalk."""
    register_dir.mkdir(parents=True, exist_ok=True)
    conn = open_db(tmp_dir / "register.duckdb")
    _entities(conn)
    _crosswalk(conn)
    write_parquet(
        conn, "SELECT * FROM crosswalk", register_dir / "crosswalk.parquet", geo=False
    )
    conn.close()
