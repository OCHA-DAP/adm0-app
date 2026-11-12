"""Rewrite the build page's files and relink them into the catalog on every save."""

from logging import INFO, basicConfig, getLogger
from pathlib import Path

from watchfiles import run_process

from pipeline.catalog import _stage_build

from . import _11_page
from .common import curated_dir, stage_dir

logger = getLogger(__name__)


def _page() -> None:
    """Run stage 11 and the catalog link step in a fresh process."""
    basicConfig(level=INFO, format="%(asctime)s - %(message)s", datefmt="%H:%M:%S")
    _11_page.main()
    _stage_build()
    logger.info("page files written")


def main() -> None:
    """Rerun ``_page`` on every change to the curated files, change lists or code."""
    lists = [stage_dir(s) / "changes.json" for s in ("05", "08")]
    run_process(curated_dir, *lists, Path(_11_page.__file__), target=_page)


if __name__ == "__main__":
    main()
