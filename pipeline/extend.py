"""Extend each source's polygons into Voronoi cells with topo-tools edge-extend."""

import sys
from argparse import ArgumentParser
from logging import getLogger
from pathlib import Path
from subprocess import run

from .config import layers, open_db, prepare_dir, tmp_dir, write_parquet

logger = getLogger(__name__)

extend_dir = tmp_dir / "extend"
TOPO_TOOLS = Path(sys.executable).parent / "topo-tools"


def extend(layer: dict) -> None:
    """Write ``layer``'s Voronoi cells from its source's polygon layer."""
    polygon = next(
        lyr["id"]
        for lyr in layers()
        if lyr["source"] == layer["source"] and lyr["kind"] == "polygon"
    )
    extend_dir.mkdir(parents=True, exist_ok=True)
    raw = extend_dir / f"{layer['id']}.parquet"
    logger.info("%s: extending %s", layer["id"], polygon)
    run(
        [TOPO_TOOLS, "edge-extend", prepare_dir / f"{polygon}.parquet", raw],
        check=True,
    )
    write_parquet(
        open_db(),
        f"SELECT * FROM read_parquet('{raw}')",
        prepare_dir / f"{layer['id']}.parquet",
    )
    raw.unlink()


def main() -> None:
    """Write one Voronoi layer per source, or only the sources named in ``--source``."""
    parser = ArgumentParser()
    parser.add_argument("--source", nargs="+")
    args, _ = parser.parse_known_args()
    for layer in layers():
        if layer["kind"] == "voronoi" and (
            not args.source or layer["source"] in args.source
        ):
            extend(layer)
