"""Write the build page's tiles and tables into their own folder."""

import json
from logging import getLogger
from pathlib import Path
from shutil import copy2

from pipeline import tiles
from pipeline.config import prepare_dir

from .common import connect, curated_dir, data, finish, stage_dir, unchanged

logger = getLogger(__name__)

LAYERS = {
    "build_units": ("05", "units"),
    "build_line_patches": ("05", "line_patches"),
    "build_cell_islands": ("05", "cell_islands"),
    "build_un": ("06", "un"),
    "build_gaul": ("06", "gaul"),
    "build_path_errors": ("06", "path_errors"),
    "build_path_disputed": ("06", "path_disputed"),
}
REF = prepare_dir / "ref.parquet"
# M49 has no row for Taiwan, which OSM border tiles name as TWN.
EXTRA_NAMES = {"TWN": "Taiwan Province of China"}


def main() -> None:
    """Tile each layer whose source changed, and copy the page's tables."""
    folder = stage_dir("08")
    sources = [Path(data(*src)) for src in LAYERS.values()]
    settings = Path(tiles.__file__)
    same_settings = unchanged("08", settings)
    conn = connect()
    for name, src in zip(LAYERS, sources, strict=True):
        dest = folder / f"{name}.pmtiles"
        if same_settings and dest.exists() and unchanged("08", src):
            logger.info("%s: unchanged", name)
        elif not conn.execute(f"SELECT count(*) FROM '{src}'").fetchall()[0][0]:
            dest.unlink(missing_ok=True)
            logger.info("%s: empty, not tiled", name)
        else:
            tiles.tile(src, dest, name)
    tables = [
        stage_dir("05") / f
        for f in ("changes.json", "changes.csv", "crosswalk.csv", "labels.geojson")
    ]
    tables += [curated_dir / "stages.json", curated_dir / "path.json"]
    for path in tables:
        copy2(path, folder)
    rows = conn.execute(
        f"SELECT iso3, name_m49 FROM '{REF}' WHERE iso3 <> ''"
    ).fetchall()
    names = dict(rows) | EXTRA_NAMES
    (folder / "names.json").write_text(json.dumps(names, ensure_ascii=False))
    finish(conn, "08", [settings, *sources, *tables, REF])
