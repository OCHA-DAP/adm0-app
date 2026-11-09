"""Paths, stage bookkeeping and reports shared by the build layer stages."""

import json
from datetime import UTC, datetime
from importlib.metadata import version
from logging import getLogger
from subprocess import check_output
from typing import TYPE_CHECKING

from pipeline.config import file_hash, input_dir, open_db, root

if TYPE_CHECKING:
    from pathlib import Path

    from duckdb import DuckDBPyConnection

logger = getLogger(__name__)

curated_dir = input_dir / "build"
build_dir = root / "outputs/build"
manifest_path = build_dir / "manifest.json"
KM2 = "ST_Area_Spheroid({}) / 1e6"
# Small pieces let overlaps use the spatial index on very large entities.
BIT_VERTICES = 128
STAGES = {
    "00": "curate",
    "01": "source",
    "02": "split",
    "03": "cut",
    "04": "attribute",
    "05": "units",
    "06": "export",
    "07": "extend",
    "08": "site",
}


def stage_dir(stage: str) -> Path:
    """Return the data folder of ``stage``, creating it when missing."""
    path = build_dir / f"{stage}_{STAGES[stage]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def data(stage: str, name: str) -> str:
    """Return the path of parquet file ``name`` in ``stage``'s folder."""
    return str(stage_dir(stage) / f"{name}.parquet")


def connect() -> DuckDBPyConnection:
    """Open an in-memory database with spatial loaded and x/y axis order."""
    conn = open_db()
    conn.execute("SET geometry_always_xy = true")
    return conn


def changes() -> list[dict]:
    """Read the curated change records."""
    return json.loads((curated_dir / "changes.json").read_text())


def path() -> list[dict]:
    """Read the page's steps."""
    return json.loads((curated_dir / "path.json").read_text())


def stages() -> list[dict]:
    """Read the plain-language stage descriptions."""
    return json.loads((curated_dir / "stages.json").read_text())


def unchanged(stage: str, path: Path) -> bool:
    """Return whether ``path`` matches ``stage``'s last inputs, with outputs intact."""
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    record = manifest.get("stages", {}).get(stage, {})
    intact = all(
        (stage_dir(stage) / name).exists() for name in record.get("outputs", {})
    )
    return intact and record.get("inputs", {}).get(
        str(path.relative_to(root))
    ) == file_hash(path)


def _figures(conn: DuckDBPyConnection, path: Path) -> dict:
    """Return the row count, and the area of a polygon file, for ``path``."""
    columns = {r[0] for r in conn.execute(f"DESCRIBE FROM '{path}'").fetchall()}
    if "geometry" not in columns:
        n = conn.execute(f"SELECT count(*) FROM '{path}'").fetchall()[0][0]
        return {"rows": n}
    n, km2 = conn.execute(f"""--sql
        SELECT count(*), sum(CASE WHEN ST_Dimension(geometry) = 2
            THEN {KM2.format("geometry")} END) FROM '{path}'
    """).fetchall()[0]
    return {"rows": n} | ({"km2": round(km2, 1)} if km2 is not None else {})


def finish(conn: DuckDBPyConnection, stage: str, inputs: list[Path]) -> None:
    """Record ``stage``'s inputs and outputs in the manifest and its README."""
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    folder = stage_dir(stage)
    outputs = {}
    for path in sorted(p for p in folder.iterdir() if p.name != "README.md"):
        figures = _figures(conn, path) if path.suffix == ".parquet" else {}
        outputs[path.name] = {"sha256": file_hash(path), **figures}
    commit = check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    manifest.setdefault("stages", {})[stage] = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": commit,
        "tools": {name: version(name) for name in ("duckdb", "topo-tools")},
        "inputs": {str(p.relative_to(root)): file_hash(p) for p in inputs},
        "outputs": outputs,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    _readme(stage, outputs)
    logger.info("stage %s: %s", stage, {k: v.get("rows") for k, v in outputs.items()})


def _readme(stage: str, outputs: dict) -> None:
    """Write the stage folder's README from its description and figures."""
    info = next(s for s in stages() if s["stage"] == stage)
    lines = [f"# {stage} {info['title']}", "", info["summary"], "", info["why"], ""]
    lines += ["| File | Rows | Area (km2) |", "|---|---:|---:|"]
    lines += [
        f"| {name} | {v.get('rows', '')} | {v.get('km2', '')} |"
        for name, v in outputs.items()
    ]
    (stage_dir(stage) / "README.md").write_text("\n".join(lines) + "\n")
