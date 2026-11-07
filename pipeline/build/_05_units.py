"""Group pieces into units, and write the crosswalk and the full change list."""

import json
from pathlib import Path
from typing import TYPE_CHECKING

from pipeline.config import write_parquet

from .common import KM2, changes, connect, curated_dir, data, finish, stage_dir

if TYPE_CHECKING:
    from collections.abc import Callable

    from duckdb import DuckDBPyConnection

VIET_NAM, VIET_NAM_XMIN = "VNM", 109.6
VIET_NAM_MOVED, VIET_NAM_REMOVED = ("C13a", "C13b"), "C13c"
UN_ATTRS = (
    "iso3cd AS un_iso3, romnam AS un_name, stscod AS un_status, isoclr AS un_sovereign"
)
GAUL_ATTRS = "GAUL0_CODE, ISO3_CODE, MAP_CODE, GAUL0_NAME"
# Smaller patches are digitising noise along shared lines.
MIN_PATCH_KM2 = 0.01
DECISIONS = curated_dir / "review_decisions.csv"


def _units(conn: DuckDBPyConnection) -> None:
    """Dissolve pieces per UN entity, GAUL entity and area into table ``units``."""
    keys = [(un, gaul, c["id"]) for c in changes() for un, gaul in c.get("keys", [])]
    conn.execute(
        "CREATE TABLE keyed (un_objectid BIGINT, gaul_id VARCHAR, change_id VARCHAR)"
    )
    conn.executemany("INSERT INTO keyed VALUES (?, ?, ?)", keys)
    conn.execute(f"""--sql
        CREATE TABLE un AS
            SELECT objectid, {UN_ATTRS} FROM '{data("01", "un_polygons")}';
        CREATE TABLE gaul AS
            SELECT gaul_id, {GAUL_ATTRS} FROM '{data("01", "gaul_polygons")}';
        CREATE TABLE units AS
            SELECT substr(md5(concat_ws(
                       '|', p.un_objectid, p.gaul_id, p.area_id)), 1, 12) AS unit_id,
                   p.un_objectid, p.gaul_id, p.area_id,
                   count(*) AS parts,
                   list(DISTINCT p.change_id) FILTER (p.change_id IS NOT NULL)
                       AS override_changes,
                   ST_Multi(ST_CollectionExtract(ST_Union_Agg(p.geometry), 3))
                       AS geometry
            FROM '{data("04", "parts")}' p GROUP BY ALL;
        CREATE TABLE tagged AS
            SELECT u.* EXCLUDE (override_changes),
                   list_distinct(list_filter(
                       list_concat(coalesce(u.override_changes, []), [k.change_id,
                           CASE WHEN k.change_id IS NULL
                                 AND n.un_iso3 IS DISTINCT FROM g.ISO3_CODE
                                THEN 'I-' || n.un_iso3 || '-' || u.gaul_id END]),
                       lambda x: x IS NOT NULL)) AS change_ids
            FROM units u
            JOIN un n ON n.objectid = u.un_objectid
            JOIN gaul g USING (gaul_id)
            LEFT JOIN keyed k USING (un_objectid, gaul_id);
        CREATE TABLE relabels (un_objectid BIGINT, gaul_id VARCHAR, change_id VARCHAR,
                               to_objectid BIGINT);
    """)
    relabels = [
        (r["un_objectid"], r["gaul_id"], c["id"], r["to"])
        for c in changes()
        if (r := c.get("relabel"))
    ]
    conn.executemany("INSERT INTO relabels VALUES (?, ?, ?, ?)", relabels)
    conn.execute("""--sql
        UPDATE tagged t SET change_ids = list_append(t.change_ids, r.change_id)
        FROM relabels r
        WHERE t.un_objectid = r.un_objectid AND t.gaul_id = r.gaul_id;
    """)


def _crosswalk(conn: DuckDBPyConnection) -> None:
    """Write the crosswalk beside the units, with every source attribute."""
    query = f"""--sql
        SELECT t.unit_id, t.area_id, t.un_objectid, n.* EXCLUDE objectid,
               t.gaul_id, g.* EXCLUDE gaul_id, t.parts,
               round({KM2.format("t.geometry")}, 3) AS km2,
               array_to_string(t.change_ids, ';') AS change_ids
        FROM tagged t
        JOIN un n ON n.objectid = t.un_objectid
        JOIN gaul g USING (gaul_id)
        ORDER BY n.un_iso3, t.un_objectid, t.gaul_id, t.area_id
    """
    write_parquet(conn, query, Path(data("05", "crosswalk")), geo=False)
    path = stage_dir("05") / "crosswalk.csv"
    conn.execute(f"COPY (FROM '{data('05', 'crosswalk')}') TO '{path}' (HEADER)")


def _record(change: dict, conn: DuckDBPyConnection) -> dict:
    """Add the units' area, box and value changes to a change that has units."""
    km2, units, box = conn.execute(f"""--sql
        SELECT round(sum({KM2.format("geometry")}), 3), count(*),
               [min(ST_XMin(geometry)), min(ST_YMin(geometry)),
                max(ST_XMax(geometry)), max(ST_YMax(geometry))]
        FROM tagged WHERE list_contains(change_ids, '{change["id"]}')
    """).fetchall()[0]
    columns = ("un_objectid", "un", "un_name", "gaul", "gaul_name", "km2")
    values = conn.execute(f"""--sql
        SELECT t.un_objectid, n.un_iso3, coalesce(n.un_name, n.un_iso3), g.MAP_CODE,
               g.GAUL0_NAME, round(sum({KM2.format("t.geometry")}), 3) AS km2
        FROM tagged t
        JOIN un n ON n.objectid = t.un_objectid JOIN gaul g USING (gaul_id)
        WHERE list_contains(t.change_ids, '{change["id"]}')
        GROUP BY ALL ORDER BY km2 DESC
    """).fetchall()
    extra = {
        "values": [
            _relabelled(change, c, conn)
            for c in (dict(zip(columns, v, strict=True)) for v in values)
        ]
    }
    if change["id"] in VIET_NAM_MOVED:
        extra |= {"gaul_removed": VIET_NAM}
    if change["id"] == VIET_NAM_REMOVED:
        parts, km2, box = conn.execute(f"""--sql
            SELECT count(*), round(sum(km2), 3),
                   [min(ST_XMin(geometry)), min(ST_YMin(geometry)),
                    max(ST_XMax(geometry)), max(ST_YMax(geometry))]
            FROM '{data("04", "removed")}'
            WHERE iso3 = '{VIET_NAM}' AND ST_XMin(geometry) > {VIET_NAM_XMIN}
        """).fetchall()[0]
        extra |= {"gaul_removed": VIET_NAM, "removed_parts": parts}
    return change | {"km2": km2, "units": units, "bbox": box} | extra


def _relabelled(change: dict, value: dict, conn: DuckDBPyConnection) -> dict:
    """Show a relabelled UN entity under the code it takes before GAUL's entity."""
    rows = conn.execute(f"""--sql
        SELECT r.change_id, r.to_objectid, n.un_iso3, coalesce(n.un_name, n.un_iso3)
        FROM relabels r
        JOIN un n ON n.objectid = r.to_objectid JOIN gaul g USING (gaul_id)
        WHERE r.un_objectid = {value["un_objectid"]}
          AND g.MAP_CODE = '{value["gaul"]}'
    """).fetchall()
    if not rows:
        return value
    change_id, objectid, code, name = rows[0]
    if change_id == change["id"]:
        return value | {"gaul": code, "gaul_name": name}
    return value | {"un_objectid": objectid, "un": code, "un_name": name}


def _islands(conn: DuckDBPyConnection) -> list[dict]:
    """Describe each UN and GAUL ownership pair no curated change covers."""
    rows = conn.execute("""--sql
        SELECT DISTINCT c, n.un_iso3, coalesce(n.un_name, n.un_iso3), t.gaul_id,
               g.GAUL0_NAME
        FROM (SELECT *, unnest(change_ids) AS c FROM tagged) t
        JOIN un n ON n.objectid = t.un_objectid JOIN gaul g USING (gaul_id)
        WHERE c LIKE 'I-%' ORDER BY c
    """).fetchall()
    return [
        {
            "id": c,
            "type": "island_ownership",
            "title": f"{un_name} in UN Geodata, {gaul_name} in GAUL",
            "description": (
                f"These islands belong to {un_name} ({iso}) in UN Geodata 2023 and to "
                f"{gaul_name} in GAUL. Each export keeps its own source's ownership."
            ),
            "keys": [],
            "method": "island attribution",
            "source": "UN Geodata and GAUL polygons",
            "comment": "",
        }
        for c, iso, un_name, _, gaul_name in rows
    ]


def _removed(conn: DuckDBPyConnection) -> list[dict]:
    """Summarize GAUL land outside UN land, one record per GAUL entity."""
    rows = conn.execute(f"""--sql
        SELECT iso3, gaul_id, round(sum(km2), 3), count(*),
               [min(ST_XMin(geometry)), min(ST_YMin(geometry)),
                max(ST_XMax(geometry)), max(ST_YMax(geometry))]
        FROM '{data("04", "removed")}'
        WHERE NOT (iso3 = '{VIET_NAM}' AND ST_XMin(geometry) > {VIET_NAM_XMIN})
        GROUP BY ALL ORDER BY 3 DESC
    """).fetchall()
    return [
        {
            "id": f"G-{gaul_id}",
            "type": "gaul_only_land",
            "title": f"GAUL land outside UN land ({iso3})",
            "description": (
                f"{parts} GAUL polygons in {iso3} touch no UN Geodata land, so they "
                "are not carried over. A later coastline choice can bring them back."
            ),
            "keys": [],
            "method": "not carried over",
            "source": "GAUL 2025",
            "comment": "",
            "km2": km2,
            "units": 0,
            "bbox": box,
            "gaul_removed": iso3,
            "removed_parts": parts,
        }
        for iso3, gaul_id, km2, parts, box in rows
    ]


def _lines(conn: DuckDBPyConnection) -> list[dict]:
    """Summarize the land GAUL and UN polygons give different entities, per border."""
    conn.execute(f"""--sql
        CREATE TEMP TABLE patches AS
        SELECT row_number() OVER () AS id, *, ST_PointOnSurface(geometry) AS point
        FROM '{data("01", "line_overlaps")}' WHERE km2 >= {MIN_PATCH_KM2};
        CREATE TEMP TABLE keyed AS
        SELECT geometry FROM tagged
        WHERE len(list_filter(change_ids, lambda x: x LIKE 'C%')) > 0;
        CREATE TEMP TABLE covered AS
        SELECT DISTINCT p.id FROM patches p
        JOIN keyed k ON ST_Intersects(k.geometry, p.point);
        CREATE TABLE line_patches AS
        SELECT a_code, b_code, least(a_code, b_code) AS x,
               greatest(a_code, b_code) AS y, km2, geometry
        FROM patches WHERE id NOT IN (SELECT id FROM covered)
    """)
    write_parquet(
        conn,
        "SELECT a_code, b_code, km2, geometry FROM line_patches",
        Path(data("05", "line_patches")),
    )
    rows = conn.execute("""--sql
        SELECT x, y, round(sum(km2), 3), count(*),
               [min(ST_XMin(geometry)), min(ST_YMin(geometry)),
                max(ST_XMax(geometry)), max(ST_YMax(geometry))],
               arg_max([ST_XMin(geometry), ST_YMin(geometry),
                        ST_XMax(geometry), ST_YMax(geometry)], km2)
        FROM line_patches GROUP BY ALL ORDER BY 3 DESC
    """).fetchall()
    return [
        {
            "id": f"L-{x}-{y}",
            "type": "line_update",
            "title": f"{x} and {y} line",
            "description": (
                f"The {x}-{y} line follows UN Geodata 2023 in both exports. The area "
                "is the land GAUL and UN Geodata polygons give different entities."
            ),
            "keys": [],
            "method": "UN line adopted",
            "source": "UN Geodata 2023",
            "comment": "",
            "km2": km2,
            "units": 0,
            "bbox": box,
            "largest_patch_bbox": largest,
            "patches": n,
        }
        for x, y, km2, n, box, largest in rows
    ]


def _island_records(
    conn: DuckDBPyConnection, prefix: str, describe: Callable[[str, str], dict]
) -> list[dict]:
    """Summarize ``cell_islands`` rows of one id prefix, one record per pair."""
    rows = conn.execute(f"""--sql
        SELECT change_id, un_iso3, any_value(un_name), cell_code, any_value(cell_name),
               round(sum(km2), 3), count(*),
               [min(ST_XMin(geometry)), min(ST_YMin(geometry)),
                max(ST_XMax(geometry)), max(ST_YMax(geometry))],
               arg_max([ST_XMin(geometry), ST_YMin(geometry),
                        ST_XMax(geometry), ST_YMax(geometry)], km2)
        FROM cell_islands WHERE change_id LIKE '{prefix}-%'
        GROUP BY change_id, un_iso3, cell_code ORDER BY 6 DESC
    """).fetchall()
    return [
        {
            "id": c,
            **describe(un_name, cell_name),
            "keys": [],
            "comment": "",
            "km2": km2,
            "units": 0,
            "bbox": box,
            "largest_patch_bbox": largest,
            "patches": n,
            "values": [
                {
                    "un": iso,
                    "un_name": un_name,
                    "gaul": cell,
                    "gaul_name": cell_name,
                    "km2": km2,
                }
            ],
        }
        for c, iso, un_name, cell, cell_name, km2, n, box, largest in rows
    ]


def _cell_islands(conn: DuckDBPyConnection) -> list[dict]:
    """Describe islands GAUL never drew, per UN owner and Voronoi cell's entity."""
    conn.execute(f"""--sql
        CREATE TEMP TABLE owned AS
        SELECT un_objectid, geometry, ST_PointOnSurface(geometry) AS point
        FROM '{data("04", "parts")}' WHERE rule = 'un_owner';
        CREATE TABLE cell_islands AS
        SELECT concat('V-', n.un_iso3, '-', v.MAP_CODE) AS change_id, n.un_iso3,
               coalesce(n.un_name, n.un_iso3) AS un_name, v.MAP_CODE AS cell_code,
               v.GAUL0_NAME AS cell_name, {KM2.format("p.geometry")} AS km2, p.geometry
        FROM owned p
        JOIN un n ON n.objectid = p.un_objectid
        JOIN '{data("01", "gaul_voronoi")}' v ON ST_Intersects(p.point, v.geometry)
    """)
    return _island_records(
        conn,
        "V",
        lambda un_name, cell_name: {
            "type": "cell_island",
            "title": f"{un_name} islands in a {cell_name} Voronoi cell",
            "description": (
                f"GAUL has no polygon for these islands, which UN Geodata gives to "
                f"{un_name}. Its Voronoi cells give them to {cell_name}, and both "
                "exports keep the UN Geodata owner."
            ),
            "method": "UN owner kept",
            "source": "UN Geodata and GAUL Voronoi cells",
        },
    )


def _island_errors(conn: DuckDBPyConnection) -> list[dict]:
    """List UN parts under review as errors, without changing any ownership."""
    conn.execute(f"""--sql
        CREATE TEMP TABLE un_parts AS
        SELECT *, ST_PointOnSurface(part) AS point FROM (
            SELECT objectid, iso3cd AS un_iso3, unnest(ST_Dump(geometry)).geom AS part
            FROM '{data("01", "un_polygons")}');
        CREATE TEMP TABLE fieldmaps_cells AS
        SELECT iso_3 AS cell_code, adm0_name1 AS cell_name,
               unnest(ST_Dump(ST_MakeValid(geometry))).geom AS cell
        FROM '{data("01", "fieldmaps_voronoi")}';
        CREATE TEMP TABLE placed AS
        SELECT p.objectid, p.un_iso3, p.part, c.cell_code, c.cell_name
        FROM un_parts p JOIN fieldmaps_cells c ON ST_Intersects(p.point, c.cell);
        INSERT INTO cell_islands
        SELECT concat('E-', p.un_iso3, '-', p.cell_code), p.un_iso3,
               coalesce(n.un_name, p.un_iso3), p.cell_code, p.cell_name,
               {KM2.format("p.part")}, p.part
        FROM placed p JOIN un n ON n.objectid = p.objectid
        WHERE upper(p.un_iso3) <> upper(p.cell_code)
          AND (p.un_iso3, p.cell_code) NOT IN (
              SELECT un, fieldmaps FROM read_csv('{DECISIONS}')
              WHERE action = 'remove')
    """)
    records = _island_records(
        conn,
        "E",
        lambda un_name, cell_name: {
            "type": "un_error",
            "title": f"{un_name} parts that FieldMaps gives to {cell_name}",
            "description": (
                f"Under review: UN Geodata's assignment gives these parts to "
                f"{un_name}, and FieldMaps gives them to {cell_name}. Ownership "
                "in both exports is unchanged."
            ),
            "method": "under review",
            "source": "UN Geodata and FieldMaps",
            "review": True,
        },
    )
    recoded = conn.execute(f"""--sql
        SELECT concat('E-', un, '-', fieldmaps) FROM read_csv('{DECISIONS}')
        WHERE action = 'recode'
    """).fetchall()
    return [_recoded(r) if (r["id"],) in recoded else r for r in records]


def _recoded(record: dict) -> dict:
    """Turn a review row into an islands row for land that only changes code."""
    value = record["values"][0]
    return record | {
        "type": "island_ownership",
        "title": f"{value['un_name']} re-coded as {value['gaul_name']}",
        "description": (
            f"GAUL disaggregates these UN Geodata parts and re-codes them from "
            f"{value['un']} to {value['gaul']}. The land is the same."
        ),
        "method": "re-coded",
    }


def _labels(conn: DuckDBPyConnection) -> None:
    """Write a label point per polygon, or per change where names replace codes."""
    rows = conn.execute(f"""--sql
        SELECT p.c,
               CASE WHEN p.c = r.change_id THEN concat(n.un_iso3, ' → ', to_un.un_iso3)
                    WHEN r.change_id IS NOT NULL
                    THEN concat(to_un.un_iso3, ' → ', g.MAP_CODE)
                    WHEN p.c IN {VIET_NAM_MOVED}
                    THEN concat('{VIET_NAM} → ', g.MAP_CODE)
                    WHEN n.un_iso3 = g.MAP_CODE
                    THEN concat(coalesce(n.un_name, 'None'), ' → ', g.GAUL0_NAME)
                    ELSE concat(n.un_iso3, ' → ', g.MAP_CODE) END,
               round({KM2.format("p.part")}, 3),
               ST_X(ST_MaximumInscribedCircle(p.part).center),
               ST_Y(ST_MaximumInscribedCircle(p.part).center)
        FROM (SELECT t.c, t.un_objectid, t.gaul_id,
                     unnest(ST_Dump(t.geometry)).geom AS part
              FROM (SELECT unnest(change_ids) AS c, un_objectid, gaul_id, geometry
                    FROM tagged) t) p
        JOIN un n ON n.objectid = p.un_objectid JOIN gaul g USING (gaul_id)
        LEFT JOIN relabels r USING (un_objectid, gaul_id)
        LEFT JOIN un to_un ON to_un.objectid = r.to_objectid
        QUALIFY n.un_iso3 != g.MAP_CODE OR p.c IN {VIET_NAM_MOVED}
             OR row_number() OVER (
                 PARTITION BY p.c ORDER BY {KM2.format("p.part")} DESC) = 1
        UNION ALL
        SELECT change_id, concat(un_iso3, ' → ', cell_code), round(km2, 3),
               ST_X(ST_MaximumInscribedCircle(geometry).center),
               ST_Y(ST_MaximumInscribedCircle(geometry).center)
        FROM cell_islands
    """).fetchall()
    features = [
        {
            "type": "Feature",
            "properties": {"change": change, "text": text, "km2": km2},
            "geometry": {"type": "Point", "coordinates": [x, y]},
        }
        for change, text, km2, x, y in rows
    ]
    collection = {"type": "FeatureCollection", "features": features}
    path = stage_dir("05") / "labels.geojson"
    path.write_text(json.dumps(collection, ensure_ascii=False))


def main() -> None:
    """Write units, crosswalk, the change list and each change's geometry."""
    conn = connect()
    _units(conn)
    write_parquet(
        conn,
        """--sql
        SELECT t.unit_id, t.un_objectid, t.gaul_id, t.area_id, t.parts,
               array_to_string(t.change_ids, ';') AS change_ids, t.geometry
        FROM tagged t""",
        Path(data("05", "units")),
    )
    _crosswalk(conn)
    cell_islands = _cell_islands(conn)
    island_errors = _island_errors(conn)
    write_parquet(
        conn,
        "SELECT change_id, km2, geometry FROM cell_islands",
        Path(data("05", "cell_islands")),
    )
    _labels(conn)
    records = [_record(c, conn) for c in [*changes(), *_islands(conn)]]
    records += island_errors + _removed(conn) + cell_islands + _lines(conn)
    out = stage_dir("05") / "changes.json"
    out.write_text(json.dumps(records, ensure_ascii=False, indent=1) + "\n")
    conn.execute(f"""--sql
        COPY (SELECT id, type, title, km2, units, method, source, description,
                     comment FROM read_json('{out}'))
        TO '{stage_dir("05") / "changes.csv"}' (HEADER)
    """)
    write_parquet(
        conn,
        """--sql
        SELECT c AS change_id,
               ST_Multi(ST_CollectionExtract(ST_Union_Agg(geometry), 3)) AS geometry
        FROM (SELECT unnest(change_ids) AS c, geometry FROM tagged) GROUP BY c""",
        Path(data("05", "change_areas")),
    )
    finish(
        conn,
        "05",
        [
            Path(data("04", "parts")),
            Path(data("04", "removed")),
            Path(data("01", "gaul_voronoi")),
            curated_dir / "changes.json",
            Path(data("01", "un_polygons")),
            Path(data("01", "fieldmaps_voronoi")),
            Path(data("01", "line_overlaps")),
            DECISIONS,
        ],
    )
