"""Link the layers and site tables into the portolan catalog and optionally push it."""

import json
from argparse import ArgumentParser
from datetime import UTC, datetime
from logging import getLogger
from typing import TYPE_CHECKING

from pipeline import fieldmaps_publish
from pipeline.config import (
    layers,
    open_db,
    prepare_dir,
    root,
    tiles_dir,
    write_parquet,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = getLogger(__name__)

CATALOG = root / "catalog"
DIFFERENCES = ("differences", "differences_dots")
TABLES = ("attributes", "items")
HOST = {
    "name": "OCHA Centre for Humanitarian Data",
    "roles": ["host"],
    "url": "https://github.com/OCHA-DAP/adm0-site/issues",
}
CC_BY = {
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
}
ODBL = {
    "license": "ODbL-1.0",
    "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
}
CC0 = {
    "license": "CC0-1.0",
    "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
}
UN_TERMS = {
    "license": "other",
    "license_url": "https://www.un.org/en/about-us/terms-of-use",
}
# Producer and licence per top-level folder; differences/ and tables/ are the site's
# own and keep the catalog's licence.
PRODUCERS = {
    "gaul": ("FAO (GAUL 2025)", CC_BY),
    "ungeodata": ("United Nations Geospatial", UN_TERMS),
    "fieldmaps": ("FieldMaps (OpenStreetMap)", ODBL),
    "wp": ("U.S. Department of State", CC0),
    "wb": ("World Bank", CC_BY),
}


def _link(src: Path, dst: Path) -> None:
    """Hardlink ``src`` to ``dst``, replacing a stale link."""
    dst.unlink(missing_ok=True)
    dst.hardlink_to(src)


def _layer_collections() -> dict[str, str]:
    """Map each tiled layer to its collection path, as catalogPath does in the site."""
    paths = {layer["id"]: f"{layer['source']}/{layer['id']}" for layer in layers()}
    paths |= {name: f"differences/{name}" for name in DIFFERENCES}
    return paths


def _stage(only: list[str] | None) -> list[Path]:
    """Lay out each collection's files, returning the collection dirs."""
    out = []
    for name, rel in _layer_collections().items():
        if only and name not in only:
            continue
        target = CATALOG / rel
        target.mkdir(parents=True, exist_ok=True)
        _link(prepare_dir / f"{name}.parquet", target / f"{name}.parquet")
        _link(tiles_dir / f"{name}.pmtiles", target / f"{name}.pmtiles")
        out.append(target)
    conn = open_db()
    for name in TABLES:
        if only and name not in only:
            continue
        target = CATALOG / "tables" / name
        target.mkdir(parents=True, exist_ok=True)
        src = tiles_dir / f"{name}.json"
        _link(src, target / src.name)
        write_parquet(
            conn, f"FROM read_json('{src}')", target / f"{name}.parquet", geo=False
        )
        out.append(target)
    return out


def _write_providers(collection: Path) -> None:
    """Write the collection's providers and licence into its .portolan/metadata.yaml."""
    producer, licence = PRODUCERS.get(collection.parent.name, (None, {}))
    providers = (
        [{"name": producer, "roles": ["producer", "licensor"]}, HOST]
        if producer
        else [{**HOST, "roles": ["producer", "licensor", "host"]}]
    )
    meta = collection / ".portolan" / "metadata.yaml"
    meta.parent.mkdir(exist_ok=True)
    meta.write_text(json.dumps({**licence, "providers": providers}, indent=2) + "\n")


def _date(collection: Path) -> str:
    mtime = (collection / f"{collection.name}.parquet").stat().st_mtime
    return datetime.fromtimestamp(mtime, UTC).date().isoformat()


def main() -> None:
    """Stage, register, check and optionally push the catalog."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", help="Stage only these layer or table ids")
    parser.add_argument("--push", action="store_true", help="Push to PORTOLAN_REMOTE")
    args, _ = parser.parse_known_args()
    for collection in _stage(args.only):
        rel = collection.relative_to(CATALOG).as_posix()
        _write_providers(collection)
        fieldmaps_publish.add(CATALOG, rel, "--datetime", _date(collection), "--force")
        logger.info("%s: added", rel)
    fieldmaps_publish.run(CATALOG, "readme")
    fieldmaps_publish.run(CATALOG, "check", "--fix", "--data-scope", "local")
    if args.push:
        fieldmaps_publish.push(CATALOG)
        logger.info("pushed")
