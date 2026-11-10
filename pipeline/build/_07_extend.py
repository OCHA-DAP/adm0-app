"""Extend the reviewed units into the surrounding water with topo-tools."""

from logging import getLogger
from pathlib import Path
from subprocess import run

from pipeline.config import THREADS, tmp_dir, write_parquet
from pipeline.extend import TOPO_TOOLS

from .common import connect, data, finish, unchanged

logger = getLogger(__name__)


def main() -> None:
    """Write ``units_voronoi``, the units grown into cells that cover the map."""
    units = Path(data("05", "units"))
    inputs = [Path(__file__), units]
    if all(unchanged("07", p) for p in inputs):
        logger.info("stage 07: inputs unchanged")
        return
    work = tmp_dir / "build_extend"
    work.mkdir(parents=True, exist_ok=True)
    raw = work / "units_voronoi.parquet"
    run(
        [TOPO_TOOLS, "edge-extend", units, raw, "--threads", str(THREADS)],
        check=True,
    )
    conn = connect()
    write_parquet(conn, f"FROM '{raw}'", Path(data("07", "units_voronoi")))
    raw.unlink()
    finish(conn, "07", inputs)
