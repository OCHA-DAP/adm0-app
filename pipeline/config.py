"""Pipeline-wide constants, source definitions and DuckDB helpers."""

import json
from logging import getLogger
from pathlib import Path

from duckdb import DuckDBPyConnection, connect

logger = getLogger(__name__)

CRS = "OGC:CRS84"
TABLE_OPTS = "FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 15"
PARQUET_OPTS = f"({TABLE_OPTS}, GEOPARQUET_VERSION V2)"
WORLD = "ST_MakeEnvelope(-180, -90, 180, 90)"
# Clips only rows past the world bounds, keeping their dimension and multi-ness.
WORLD_CLIP = f"""CASE
    WHEN ST_IsEmpty(geometry) OR (
        ST_XMin(geometry) >= -180 AND ST_XMax(geometry) <= 180
        AND ST_YMin(geometry) >= -90 AND ST_YMax(geometry) <= 90
    ) THEN geometry
    WHEN NOT ST_Intersects(geometry, {WORLD})
    THEN error('geometry lies entirely outside the world bounds')
    ELSE (SELECT CASE WHEN starts_with(ST_GeometryType(geometry)::VARCHAR, 'MULTI')
        THEN ST_Multi(g) ELSE g END
        FROM (SELECT ST_CollectionExtract(ST_Intersection(
            ST_MakeValid(geometry), {WORLD}), ST_Dimension(geometry) + 1) AS g))
    END"""

root = Path(__file__).parent.parent
tmp_dir = root / "tmp"
download_dir = tmp_dir / "download"
prepare_dir = tmp_dir / "prepare"
fieldmaps_dir = tmp_dir / "fieldmaps"
register_dir = root / "outputs/register"
tiles_dir = root / "outputs/tiles"
input_dir = root / "inputs"
layers_json = root / "site/src/lib/layers.json"

BASELINE = "gaul"

# Per source: entity id, join code and register entity name (default name), then
# attribute columns (output name: SQL).
SOURCE_COLUMNS = {
    "gaul": {
        "id": "gaul_id",
        "code": "ISO3_CODE",
        "name": "GAUL0_NAME",
        "region": "CONTINENT",
    },
    "ungeodata": {
        "id": "iso3cd || coalesce('-' || romnam, '')",
        "code": "iso3cd",
        "name": "romnam",
        "mapname": "maplab",
        "sovereign": "isoclr",
        "status": "status_label",
        "region": "contcd",
    },
    "fieldmaps": {
        "id": "adm0_id",
        "code": "iso_3",
        "entity": "adm0_name",
        "name": "adm0_name1",
        "mapname": "adm0_name",
        "sovereign": "iso_3_grp",
        "status": "status_nm",
        "region": "region1_nm",
    },
    "wp": {
        "id": "WP_ID",
        "code": "GENC_3",
        "name": "WP_Name",
        "mapname": "Map_Label",
        "status": "US_Recog",
    },
    "unterm": {"code": "iso3", "name": "name_en_short", "status": "un_status"},
    "m49": {"code": "iso3", "name": "name_m49", "region": "region"},
}


def layers() -> list[dict]:
    """Map layers shared with the site, one per PMTiles file."""
    return json.loads(layers_json.read_text())


def open_db(path: Path | None = None) -> DuckDBPyConnection:
    """Connect with spatial loaded, to a fresh file at ``path`` or in memory."""
    if path:
        path.unlink(missing_ok=True)
    conn = connect(path or ":memory:")
    conn.execute("LOAD spatial")
    return conn


def write_parquet(
    conn: DuckDBPyConnection, query: str, out: Path, *, geo: bool = True
) -> None:
    """Write ``query`` to ``out``, as clipped Hilbert-sorted GeoParquet when ``geo``."""
    if geo:
        query = f"""SELECT * FROM (
            SELECT * REPLACE (ST_SetCRS({WORLD_CLIP}, '{CRS}') AS geometry)
            FROM ({query})) ORDER BY ST_Hilbert(geometry, ST_Extent({WORLD}))"""
    conn.execute(
        f"COPY ({query}) TO '{out}' {PARQUET_OPTS if geo else f'({TABLE_OPTS})'}"
    )
    if not geo:
        n = conn.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchall()[0][0]
        logger.info("%s: %d rows", out.stem, n)
        return
    n, crs, xmin, ymin, xmax, ymax = conn.execute(f"""--sql
        SELECT count(*), any_value(ST_CRS(geometry)), min(ST_XMin(geometry)),
            min(ST_YMin(geometry)), max(ST_XMax(geometry)), max(ST_YMax(geometry))
        FROM read_parquet('{out}')""").fetchall()[0]
    if n and (crs != CRS or xmin < -180 or ymin < -90 or xmax > 180 or ymax > 90):  # noqa: PLR2004
        msg = f"{out.name}: CRS {crs}, bbox {xmin, ymin, xmax, ymax}"
        raise ValueError(msg)
    logger.info("%s: %d rows", out.stem, n)
