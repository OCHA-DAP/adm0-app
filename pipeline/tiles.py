"""Write one PMTiles file per source layer for the comparison map."""

from argparse import ArgumentParser
from logging import getLogger
from pathlib import Path

import tylertoo

from .config import fresh, layers, prepare_dir, record, tiles_dir

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
    """Tile each layer whose source or settings changed, or exactly ``--only``."""
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
        src, dest = prepare_dir / f"{name}.parquet", tiles_dir / f"{name}.pmtiles"
        inputs = [src, Path(__file__)]
        if not args.only and fresh(f"tiles/{name}", inputs, [dest]):
            logger.info("%s: unchanged", name)
            continue
        tile(src, dest, name)
        record(f"tiles/{name}", inputs)
        logger.info("%s: tiled", name)
