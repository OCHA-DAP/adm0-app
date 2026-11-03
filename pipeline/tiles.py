"""Write one PMTiles file per source layer for the comparison map."""

from argparse import ArgumentParser
from logging import getLogger
from typing import TYPE_CHECKING

import tylertoo

from .config import layers, prepare_dir, tiles_dir

if TYPE_CHECKING:
    from pathlib import Path

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

# Island dots all stay at every zoom.
EXTRA = {
    "differences_dots": {"point_thinning": 0},
}


def tile(src: Path, dest: Path, name: str) -> None:
    """Tile ``src`` into ``dest`` as layer ``name``, keeping every feature."""
    overview = dest.with_suffix(".overview.parquet")
    tylertoo.overview(
        str(src), str(overview), max_zoom=MAX_ZOOM, **KEEP_ALL, **EXTRA.get(name, {})
    )
    tylertoo.export_pmtiles(
        str(overview), str(dest), layer_name=name, tile_size_limit=None
    )
    overview.unlink()


def main() -> None:
    """Build an overview and PMTiles for each prepared layer, or only ``--only``."""
    parser = ArgumentParser()
    parser.add_argument("--only", nargs="+")
    args, _ = parser.parse_known_args()
    tiles_dir.mkdir(parents=True, exist_ok=True)
    names = [layer["id"] for layer in layers()]
    # Written by the optional differences step.
    names += [
        name
        for name in ("differences", "differences_dots")
        if (prepare_dir / f"{name}.parquet").exists()
    ]
    for name in [n for n in names if not args.only or n in args.only]:
        tile(prepare_dir / f"{name}.parquet", tiles_dir / f"{name}.pmtiles", name)
        logger.info("%s: tiled", name)
