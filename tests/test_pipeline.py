"""Check the pipeline's shared skip records and the differences it writes."""

from math import comb
from typing import TYPE_CHECKING

import pytest
from duckdb import connect

from pipeline import config
from pipeline.config import register_dir

if TYPE_CHECKING:
    from pathlib import Path

MIN_MATCHES = 10000
MIN_LAND_PATCHES = 3000000


@pytest.fixture
def files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Point the records at ``tmp_path`` and return an input and an output."""
    monkeypatch.setattr(config, "root", tmp_path)
    monkeypatch.setattr(config, "state_path", tmp_path / "state.json")
    source, built = tmp_path / "source.txt", tmp_path / "built.txt"
    source.write_text("a")
    built.write_text("b")
    return source, built


def test_fresh_needs_a_record(files: tuple[Path, Path]) -> None:
    """Nothing counts as built until it is recorded."""
    source, built = files
    assert not config.fresh("key", [source], [built])
    config.record("key", [source])
    assert config.fresh("key", [source], [built])


def test_fresh_follows_inputs_and_outputs(files: tuple[Path, Path]) -> None:
    """A changed input or a missing output means a rebuild."""
    source, built = files
    config.record("key", [source])
    source.write_text("c")
    assert not config.fresh("key", [source], [built])
    config.record("key", [source])
    built.unlink()
    assert not config.fresh("key", [source], [built])


@pytest.mark.skipif(
    not (register_dir / "matches.parquet").exists(),
    reason="run `python -m pipeline --step differences` first",
)
def test_register_is_complete() -> None:
    """Every source pair has matches, and land patches stay in their millions."""
    db = connect()
    pairs, matches = db.execute(f"""--sql
        SELECT count(DISTINCT pair), count(*)
        FROM '{register_dir / "matches.parquet"}'
    """).fetchall()[0]
    patches = db.execute(f"""--sql
        SELECT count(*) FROM '{register_dir / "land.parquet"}'
    """).fetchall()[0][0]
    assert pairs == comb(len({lyr["source"] for lyr in config.layers()}), 2)
    assert matches > MIN_MATCHES
    assert patches > MIN_LAND_PATCHES
