"""Extend each source's polygons into Voronoi cells with topo-tools edge-extend."""

import sys
from argparse import ArgumentParser
from logging import getLogger
from pathlib import Path
from subprocess import run

from .config import fresh, layers, open_db, prepare_dir, record, tmp_dir, write_parquet

logger = getLogger(__name__)

extend_dir = tmp_dir / "extend"
TOPO_TOOLS = Path(sys.executable).parent / "topo-tools"


def _polygons(layer: dict) -> Path:
    """Return the prepared polygon file of ``layer``'s source."""
    polygon = next(
        lyr["id"]
        for lyr in layers()
        if lyr["source"] == layer["source"] and lyr["kind"] == "polygon"
    )
    return prepare_dir / f"{polygon}.parquet"


def extend(layer: dict) -> None:
    """Write ``layer``'s Voronoi cells from its source's polygon layer."""
    polygons = _polygons(layer)
    extend_dir.mkdir(parents=True, exist_ok=True)
    raw = extend_dir / f"{layer['id']}.parquet"
    logger.info("%s: extending %s", layer["id"], polygons.stem)
    run(
        [TOPO_TOOLS, "edge-extend", polygons, raw],
        check=True,
    )
    write_parquet(
        open_db(),
        f"SELECT * FROM read_parquet('{raw}')",
        prepare_dir / f"{layer['id']}.parquet",
    )
    raw.unlink()
    record(f"extend/{layer['id']}", [polygons])


def main() -> None:
    """Extend each source whose polygons changed, or exactly those in ``--source``."""
    parser = ArgumentParser()
    parser.add_argument("--source", nargs="+")
    args, _ = parser.parse_known_args()
    for layer in (lyr for lyr in layers() if lyr["kind"] == "voronoi"):
        if args.source:
            if layer["source"] in args.source:
                extend(layer)
        elif fresh(
            f"extend/{layer['id']}",
            [_polygons(layer)],
            [prepare_dir / f"{layer['id']}.parquet"],
        ):
            logger.info("%s: unchanged", layer["id"])
        else:
            extend(layer)
