"""Integration tests for the vendored portolan wrapper on a scratch catalog."""

import json
from typing import TYPE_CHECKING

import pytest

from pipeline import fieldmaps_publish
from pipeline.catalog import HOST
from pipeline.config import open_db, write_parquet
from pipeline.tiles import tile

if TYPE_CHECKING:
    from pathlib import Path

# Enough same-stem collections that directory listing order varies across them.
COLLECTIONS = 12
PROVIDERS = {"providers": [{**HOST, "roles": ["producer", "licensor", "host"]}]}


@pytest.fixture(scope="module")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a catalog of collections that each hold <stem>.parquet and its PMTiles."""
    root = tmp_path_factory.mktemp("catalog")
    src = root.parent / "zone.parquet"
    write_parquet(open_db(), "SELECT 1 AS id, ST_Point(10, 20) AS geometry", src)
    tiles = root.parent / "zone.pmtiles"
    tile(src, tiles, "zone")
    fieldmaps_publish.run(root, "init", "--auto", "--license", "ODbL-1.0")
    for i in range(COLLECTIONS):
        collection = root / f"p{i}"
        collection.mkdir()
        (collection / f"zone{i}.parquet").hardlink_to(src)
        (collection / f"zone{i}.pmtiles").hardlink_to(tiles)
        (collection / ".portolan").mkdir()
        (collection / ".portolan" / "metadata.yaml").write_text(json.dumps(PROVIDERS))
        fieldmaps_publish.add(root, f"p{i}", "--datetime", "2026-01-01")
    return root


@pytest.mark.parametrize("i", range(COLLECTIONS))
def test_add_keys_parquet_and_tiles_apart(catalog: Path, i: int) -> None:
    """The parquet keeps <stem>, its PMTiles gets <stem>-tiles and a pmtiles link."""
    data = json.loads((catalog / f"p{i}" / "collection.json").read_text())
    assets = {k: a["href"].removeprefix("./") for k, a in data["assets"].items()}
    assert assets[f"zone{i}"] == f"zone{i}.parquet"
    assert assets[f"zone{i}-tiles"] == f"zone{i}.pmtiles"
    links = [x["href"] for x in data["links"] if x["rel"] == "pmtiles"]
    assert [x.removeprefix("./") for x in links] == [f"zone{i}.pmtiles"]


def test_add_leaves_source_parquet_untouched(catalog: Path) -> None:
    """Hardlinked pipeline outputs must not be rewritten by add."""
    src = (catalog.parent / "zone.parquet").read_bytes()
    assert (catalog / "p0" / "zone0.parquet").read_bytes() == src


def test_check_passes(catalog: Path) -> None:
    """The catalog validates with no errors."""
    envelope = fieldmaps_publish.run(catalog, "check", "--data-scope", "local")
    assert envelope["data"]["error_count"] == 0


def test_run_raises_on_failure(catalog: Path) -> None:
    """A failed command raises naming the command."""
    with pytest.raises(RuntimeError, match="portolan add missing"):
        fieldmaps_publish.run(catalog, "add", "missing")
