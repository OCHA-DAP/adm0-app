"""Pipeline-wide constants, source definitions and DuckDB helpers."""

import json
from logging import getLogger
from pathlib import Path

from duckdb import DuckDBPyConnection, connect

logger = getLogger(__name__)

CRS = "OGC:CRS84"
PARQUET_OPTS = "(FORMAT PARQUET, COMPRESSION ZSTD, GEOPARQUET_VERSION V2)"

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
        "id": "id",
        "code": "iso_3",
        "entity": "adm0_name",
        "name": "adm0_name1",
        "mapname": "adm0_name",
        "sovereign": "iso_3_grp",
        "status": "status_nm",
        "region": "region1_nm",
    },
    "wp": {
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
    """Write ``query`` to ``out``, as CRS84 GeoParquet when ``geo``, and log rows."""
    if geo:
        query = f"""SELECT * REPLACE (ST_SetCRS(geometry, '{CRS}') AS geometry)
            FROM ({query})"""
    opts = PARQUET_OPTS if geo else "(FORMAT PARQUET, COMPRESSION ZSTD)"
    conn.execute(f"COPY ({query}) TO '{out}' {opts}")
    n = conn.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    logger.info("%s: %d rows", out.stem, n)
