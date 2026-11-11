"""Tile the build page's map layers into their own folder."""

from logging import getLogger
from pathlib import Path

from pipeline import tiles

from .common import connect, data, finish, stage_dir, unchanged

logger = getLogger(__name__)

LAYERS = {
    "build_units": ("05", "units"),
    "build_line_patches": ("05", "line_patches"),
    "build_cell_islands": ("05", "cell_islands"),
    "build_un": ("06", "un"),
    "build_gaul": ("06", "gaul"),
    "build_path_errors": ("06", "path_errors"),
    "build_path_disputed": ("06", "path_disputed"),
    "build_land_areas": ("05", "land_areas"),
    "build_coast_un": ("08", "un"),
    "build_new_islands": ("08", "new_islands"),
    "build_dropped": ("08", "dropped"),
    "build_gained": ("08", "gained"),
    "build_lost": ("08", "lost"),
}


def main() -> None:
    """Tile each layer whose source changed."""
    folder = stage_dir("09")
    sources = [Path(data(*src)) for src in LAYERS.values()]
    settings = Path(tiles.__file__)
    same_settings = unchanged("09", settings)
    conn = connect()
    for name, src in zip(LAYERS, sources, strict=True):
        dest = folder / f"{name}.pmtiles"
        if same_settings and dest.exists() and unchanged("09", src):
            logger.info("%s: unchanged", name)
        elif not conn.execute(f"SELECT count(*) FROM '{src}'").fetchall()[0][0]:
            dest.unlink(missing_ok=True)
            logger.info("%s: empty, not tiled", name)
        else:
            tiles.tile(src, dest, name)
    finish(conn, "09", [settings, *sources])
