"""Write one PMTiles file per source layer for the comparison map."""

from logging import getLogger

import tylertoo

from .config import layers, prepare_dir, tiles_dir

logger = getLogger(__name__)

MAX_ZOOM = 12
# Every boundary must render at every zoom, so only sub-pixel simplification drops.
KEEP_ALL = {
    "density_drop": False,
    "line_thinning": 0,
    "line_visibility": 0,
    "polygon_thinning": 0,
    "polygon_visibility": 0,
}


def main() -> None:
    """Build an overview and PMTiles for each prepared layer."""
    tiles_dir.mkdir(parents=True, exist_ok=True)
    for name in (layer["id"] for layer in layers()):
        src = prepare_dir / f"{name}.parquet"
        overview = tiles_dir / f"{name}.overview.parquet"
        tylertoo.overview(str(src), str(overview), max_zoom=MAX_ZOOM, **KEEP_ALL)
        tylertoo.export_pmtiles(
            str(overview),
            str(tiles_dir / f"{name}.pmtiles"),
            layer_name=name,
            tile_size_limit=None,
        )
        overview.unlink()
        logger.info("%s: tiled", name)
