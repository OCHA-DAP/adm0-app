"""Write the build page's change list, text and tables into their own folder."""

import json
from shutil import copy2

from pipeline.config import prepare_dir

from .common import STEPS, connect, curated_dir, finish, stage_dir

REF = prepare_dir / "ref.parquet"
DESCRIPTIONS = curated_dir / "descriptions.json"
PATH = curated_dir / "path.json"
# M49 has no row for Taiwan, which OSM border tiles name as TWN.
EXTRA_NAMES = {"TWN": "Taiwan Province of China"}


def _coast_text(c: dict) -> str:
    """Describe the land an entity gains, loses, drops and adds along its coast."""
    parts = [f"gains {c['gained_km2']:,.1f} km²", f"loses {c['lost_km2']:,.1f} km²"]
    if c["dropped_km2"]:
        parts.append(f"drops {c['dropped_km2']:,.1f} km² of islands")
    if c["islands"]:
        parts.append(f"adds {c['islands']} islands ({c['added_km2']:,.1f} km²)")
    return (
        f"{c['values'][0]['un_name']} {', '.join(parts[:-1])} and {parts[-1]} "
        "along its coast."
    )


def _generated(c: dict) -> dict:
    """Return the title, text, method and source of a record the build lists."""
    v = (c.get("values") or [{}])[0]
    if c["type"] == "line_update":
        x, y = c["codes"]
        return {
            "title": f"{x} and {y} line",
            "method": "UN line adopted",
            "source": "UN Geodata 2023",
        }
    if c["type"] == "un_error":
        un, cell = v["un_name"], v["gaul_name"]
        return {
            "title": f"{un} parts that likely belong to {cell}",
            "text": f"These parts likely belong to {cell}.",
            "method": "not applied",
            "source": "UN Geodata",
        }
    if c["type"] == "coast":
        return {
            "title": f"{v['un_name']} coastline",
            "text": _coast_text(c),
            "method": "OSM land clipped to the extended units",
            "source": "OpenStreetMap land polygons",
        }
    if c["type"] == "land_area":
        return {
            "title": v["gaul_name"],
            "method": "information only, not applied",
            "source": "Disputed area outlines",
        }
    if c["type"] == "new_island":
        return {
            "title": f"{v['un_name']}, a new entity",
            "method": "Voronoi cell",
            "source": "OpenStreetMap land polygons",
        }
    return {}


def _described(records: list[dict]) -> list[dict]:
    """Give each record its title and text, curated text first, with sources."""
    curated = json.loads(DESCRIPTIONS.read_text())
    required = [
        c["id"]
        for c in records
        if c["id"][0] == "C" or c["type"] in ("new_island", "land_area")
    ]
    untitled = [
        i for i in required if i[0] == "C" and not curated.get(i, {}).get("title")
    ]
    if (
        missing := [i for i in required if not curated.get(i, {}).get("sources")]
        + untitled
    ):
        msg = f"no description with sources in {DESCRIPTIONS.name}: {missing}"
        raise ValueError(msg)
    if unknown := sorted(set(curated) - {c["id"] for c in records}):
        msg = f"{DESCRIPTIONS.name} has unknown ids: {unknown}"
        raise ValueError(msg)
    for c in records:
        entry = curated.get(c["id"], {})
        auto = {} if c["id"][0] == "C" else _generated(c)
        texts = [entry.get("text"), auto.get("text")]
        c["title"] = entry.get("title") or auto["title"]
        c["description"] = " ".join(t.strip() for t in texts if t)
        c["method"] = entry.get("method") or auto["method"]
        c["source"] = entry.get("source") or auto["source"]
        c["sources"] = entry.get("sources", [])
    return records


def _steps() -> list[dict]:
    """Return the page's steps with the change types each applies."""
    steps = json.loads(PATH.read_text())
    if [s["id"] for s in steps] != list(STEPS):
        msg = f"path.json steps differ from {list(STEPS)}"
        raise ValueError(msg)
    return [s | {"types": STEPS[s["id"]]} for s in steps]


def main() -> None:
    """Write the described change list, the page's steps and the tables it loads."""
    folder = stage_dir("10")
    conn = connect()
    lists = [stage_dir(s) / "changes.json" for s in ("05", "08")]
    merged = _described([c for path in lists for c in json.loads(path.read_text())])
    out = folder / "changes.json"
    out.write_text(json.dumps(merged, ensure_ascii=False))
    conn.execute(f"""--sql
        COPY (SELECT id, type, title, km2, units, method, source, description
              FROM read_json('{out}'))
        TO '{folder / "changes.csv"}' (HEADER)
    """)
    rows = conn.execute(
        f"SELECT iso3, name_m49 FROM '{REF}' WHERE iso3 <> ''"
    ).fetchall()
    names = dict(rows) | EXTRA_NAMES
    (folder / "names.json").write_text(json.dumps(names, ensure_ascii=False))
    tables = [stage_dir("05") / f for f in ("crosswalk.csv", "labels.geojson")]
    tables.append(curated_dir / "stages.json")
    for path in tables:
        copy2(path, folder)
    (folder / "path.json").write_text(json.dumps(_steps(), ensure_ascii=False))
    finish(conn, "10", [*tables, *lists, PATH, DESCRIPTIONS, REF])
