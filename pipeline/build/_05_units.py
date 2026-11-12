"""Group pieces into units, and write the crosswalk and the full change list."""

import json
from pathlib import Path
from typing import TYPE_CHECKING

from pipeline.config import write_parquet

from .common import (
    KM2,
    STEPS,
    changes,
    connect,
    curated_dir,
    data,
    finish,
    names,
    stage_dir,
)

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

UN_ATTRS = (
    "iso3cd AS un_iso3, coalesce(f.name, romnam) AS un_name, "
    "stscod AS un_status, isoclr AS un_sovereign"
)
GAUL_ATTRS = "GAUL0_CODE, ISO3_CODE, MAP_CODE, GAUL0_NAME"
# Smaller patches are digitising noise along shared lines.
MIN_PATCH_KM2 = 0.01
DECISIONS = curated_dir / "review_decisions.csv"
OVERRIDES = curated_dir / "island_overrides.csv"
LINKS = curated_dir / "gaul_links.csv"
LAND = curated_dir / "land_areas.parquet"
# Smaller shares are where an outline and UN Geodata's lines differ.
MIN_LAND_SHARE = 0.05


def _units(conn: DuckDBPyConnection) -> None:
    """Dissolve pieces per UN entity, GAUL entity and area into table ``units``."""
    # Stage 04 already tags area changes per area; joining their keys here duplicates.
    keys = [
        (un, gaul, c["id"])
        for c in changes()
        if not c.get("areas")
        for un, gaul in c.get("keys", [])
    ]
    conn.execute(
        "CREATE TABLE keyed (un_objectid BIGINT, gaul_id VARCHAR, change_id VARCHAR)"
    )
    conn.executemany("INSERT INTO keyed VALUES (?, ?, ?)", keys)
    conn.execute(
        "CREATE TABLE entities (change_id VARCHAR, code VARCHAR, name VARCHAR)"
    )
    conn.executemany(
        "INSERT INTO entities VALUES (?, ?, ?)",
        [(c["id"], e["code"], e["name"]) for c in changes() if (e := c.get("entity"))],
    )
    # Every step but the split one applies to the UN layer too.
    shared = {t for s, types in STEPS.items() if s != "split" for t in types}
    conn.execute("CREATE TABLE moves (change_id VARCHAR, to_objectid BIGINT)")
    conn.executemany(
        "INSERT INTO moves VALUES (?, ?)",
        [(c["id"], c.get("un_to")) for c in changes() if c["type"] in shared],
    )
    conn.execute(f"""--sql
        CREATE TABLE un AS
            SELECT objectid, {UN_ATTRS} FROM '{data("01", "un_polygons")}'
            LEFT JOIN ({names()}) f ON f.code = iso3cd;
        CREATE TABLE gaul AS
            SELECT gaul_id, {GAUL_ATTRS} FROM '{data("01", "gaul_polygons")}';
        CREATE TABLE units AS
            SELECT substr(md5(concat_ws(
                       '|', p.un_objectid, p.gaul_id, p.area_id, p.piece)), 1, 12)
                       AS unit_id,
                   p.un_objectid, p.gaul_id, p.area_id, p.piece,
                   count(*) AS parts,
                   list(DISTINCT p.change_id) FILTER (p.change_id IS NOT NULL)
                       AS override_changes,
                   ST_Multi(ST_CollectionExtract(ST_Union_Agg(p.geometry), 3))
                       AS geometry
            FROM '{data("04", "parts")}' p GROUP BY ALL;
        CREATE TABLE tagged AS
            SELECT u.* EXCLUDE (override_changes),
                   list_distinct(list_filter(
                       list_concat(coalesce(u.override_changes, []), [k.change_id]),
                       lambda x: x IS NOT NULL)) AS change_ids
            FROM units u
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
    conn.execute(f"""--sql
        UPDATE tagged t SET change_ids = list_append(t.change_ids, r.change_id)
        FROM relabels r
        WHERE t.un_objectid = r.un_objectid AND t.gaul_id = r.gaul_id;
        CREATE TABLE back AS
        SELECT gaul_id, any_value(un_objectid) AS un_objectid
        FROM read_csv('{LINKS}', types={{'gaul_id': 'VARCHAR'}})
        GROUP BY gaul_id HAVING count(*) = 1;
        CREATE OR REPLACE TABLE tagged AS
        SELECT t.* EXCLUDE (geometry),
               (SELECT any_value(code) FROM entities e
                WHERE list_contains(t.change_ids, e.change_id)) AS entity,
               CASE WHEN list_has_any(t.change_ids, (SELECT list(change_id) FROM moves))
                    THEN coalesce((SELECT any_value(to_objectid) FROM moves m
                                   WHERE list_contains(t.change_ids, m.change_id)),
                                  (SELECT any_value(un_objectid) FROM back b
                                   WHERE b.gaul_id = t.gaul_id),
                                  t.un_objectid)
                    ELSE t.un_objectid END AS un_owner,
               t.geometry
        FROM tagged t;
        CREATE TABLE links AS
        SELECT DISTINCT upper(n.un_iso3) AS un, upper(g.ISO3_CODE) AS gaul
        FROM tagged t JOIN un n ON n.objectid = t.un_objectid
        JOIN gaul g USING (gaul_id)
        WHERE len(t.change_ids) = 0 AND upper(n.un_iso3) <> upper(g.ISO3_CODE);
    """)


def _adm0(conn: DuckDBPyConnection) -> None:
    """Give each unit its output row: code, number within the code and name."""
    conn.execute("CREATE TABLE area_codes (area_id VARCHAR, code VARCHAR)")
    conn.executemany(
        "INSERT INTO area_codes VALUES (?, ?)",
        [(a, code) for c in changes() for a, code in c.get("area_codes", {}).items()],
    )
    fieldmaps = data("01", "fieldmaps_voronoi")
    conn.execute(f"""--sql
        CREATE TABLE grouped AS
        SELECT t.unit_id, t.piece,
               coalesce('P ' || t.piece, 'A ' || a.code, 'N ' || t.entity,
                        'G ' || t.gaul_id) AS grp,
               coalesce(t.entity, a.code, f.iso_3, g.ISO3_CODE) AS iso3,
               coalesce(f.adm0_name, n.name, e.name, g.GAUL0_NAME) AS name,
               {KM2.format("t.geometry")} AS km2,
               len(list_filter(t.change_ids, lambda x: x LIKE 'C%')) > 0 AS curated,
               -- UN stscod 2 to 4: Occupied Palestinian Territory, NSGT, Territory
               u.un_status IN (2, 3, 4) AS territory
        FROM tagged t
        LEFT JOIN un u ON u.objectid = t.un_objectid
        LEFT JOIN area_codes a USING (area_id)
        LEFT JOIN (SELECT DISTINCT adm0_id, iso_3, adm0_name FROM '{fieldmaps}') f
          ON f.adm0_id = t.piece
        LEFT JOIN ({names()}) n ON n.code = a.code
        LEFT JOIN (SELECT DISTINCT code, name FROM entities) e ON e.code = t.entity
        LEFT JOIN gaul g USING (gaul_id);
        CREATE TABLE numbered AS
        SELECT *, row_number() OVER (PARTITION BY iso3 ORDER BY km2 DESC) AS rank,
               CASE WHEN count(*) OVER (PARTITION BY iso3) > 1
                    THEN iso3 || '_' || rank ELSE iso3 END AS adm0_id
        FROM (SELECT grp, any_value(iso3) AS iso3, any_value(name) AS name,
                     sum(km2) AS km2, bool_or(piece IS NOT NULL) AS pieced,
                     bool_or(curated) AS curated, bool_or(territory) AS territory
              FROM grouped GROUP BY grp);
        CREATE TABLE unit_adm0 AS
        SELECT g.unit_id, n.adm0_id, n.iso3, n.name AS adm0_name
        FROM grouped g JOIN numbered n USING (grp);
        UPDATE tagged t SET change_ids = list_append(t.change_ids, 'S-' || n.adm0_id)
        FROM grouped g JOIN numbered n USING (grp)
        WHERE g.unit_id = t.unit_id AND n.pieced AND NOT n.curated
          AND (n.rank > 1 OR n.territory);
    """)


def _crosswalk(conn: DuckDBPyConnection) -> None:
    """Write the crosswalk beside the units, with every source attribute."""
    query = f"""--sql
        SELECT t.unit_id, a.adm0_id, a.iso3, t.area_id, t.un_objectid,
               n.* EXCLUDE objectid,
               t.gaul_id, g.* EXCLUDE gaul_id, t.entity, e.name AS entity_name,
               t.un_owner,
               t.parts,
               round({KM2.format("t.geometry")}, 3) AS km2,
               array_to_string(t.change_ids, ';') AS change_ids
        FROM tagged t
        JOIN un n ON n.objectid = t.un_objectid
        LEFT JOIN gaul g USING (gaul_id)
        LEFT JOIN (SELECT DISTINCT code, name FROM entities) e ON e.code = t.entity
        JOIN unit_adm0 a USING (unit_id)
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
    after = (
        "a.iso3, a.adm0_name"
        if change["type"] in STEPS["split"]
        else "coalesce(t.entity, g.MAP_CODE), coalesce(e.name, g.GAUL0_NAME)"
    )
    values = conn.execute(f"""--sql
        SELECT t.un_objectid, n.un_iso3, coalesce(n.un_name, n.un_iso3), {after},
               round(sum({KM2.format("t.geometry")}), 3) AS km2
        FROM tagged t
        JOIN un n ON n.objectid = t.un_objectid LEFT JOIN gaul g USING (gaul_id)
        LEFT JOIN entities e ON e.code = t.entity
        JOIN unit_adm0 a USING (unit_id)
        WHERE list_contains(t.change_ids, '{change["id"]}')
        GROUP BY ALL ORDER BY km2 DESC
    """).fetchall()
    extra = {
        "values": [
            _relabelled(change, c, conn)
            for c in (dict(zip(columns, v, strict=True)) for v in values)
        ]
    }
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
        # A display name for codes UN Geodata leaves unnamed.
        return value | {"gaul": code, "gaul_name": change["relabel"].get("name", name)}
    return value | {"un_objectid": objectid, "un": code, "un_name": name}


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
          AND (upper(b_code), upper(a_code)) NOT IN (SELECT un, gaul FROM links)
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
            "codes": [x, y],
            "keys": [],
            "km2": km2,
            "units": 0,
            "bbox": box,
            "largest_patch_bbox": largest,
            "patches": n,
        }
        for x, y, km2, n, box, largest in rows
    ]


def _island_records(conn: DuckDBPyConnection, prefix: str, fields: dict) -> list[dict]:
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
            **fields,
            "keys": [],
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


def _island_errors(conn: DuckDBPyConnection) -> list[dict]:
    """List UN parts FieldMaps gives elsewhere that no change moves yet."""
    conn.execute(f"""--sql
        CREATE TEMP TABLE un_parts AS
        SELECT un_objectid AS objectid, un_iso3, geometry AS part,
               ST_PointOnSurface(geometry) AS point
        FROM '{data("02", "un_parts")}'
        WHERE (un_objectid, un_part) NOT IN (
            SELECT un_objectid, un_part FROM read_csv('{OVERRIDES}')
            WHERE un_part IS NOT NULL);
        CREATE TEMP TABLE fieldmaps_cells AS
        SELECT iso_3 AS cell_code, adm0_name1 AS cell_name,
               unnest(ST_Dump(ST_MakeValid(geometry))).geom AS cell
        FROM '{data("01", "fieldmaps_voronoi")}';
        CREATE TEMP TABLE placed AS
        SELECT p.objectid, p.un_iso3, p.part, c.cell_code, c.cell_name
        FROM un_parts p JOIN fieldmaps_cells c ON ST_Intersects(p.point, c.cell);
        CREATE TABLE cell_islands AS
        SELECT concat('E-', p.un_iso3, '-', p.cell_code) AS change_id, p.un_iso3,
               coalesce(n.un_name, p.un_iso3) AS un_name, p.cell_code, p.cell_name,
               {KM2.format("p.part")} AS km2, p.part AS geometry
        FROM placed p JOIN un n ON n.objectid = p.objectid
        WHERE upper(p.un_iso3) <> upper(p.cell_code)
          AND (upper(p.un_iso3), upper(p.cell_code)) NOT IN (SELECT un, gaul FROM links)
          AND (p.un_iso3, p.cell_code) NOT IN (
              SELECT un, fieldmaps FROM read_csv('{DECISIONS}')
              WHERE action = 'remove')
    """)
    return _island_records(
        conn,
        "E",
        {"type": "un_error", "review": True},
    )


def _land(conn: DuckDBPyConnection) -> list[dict]:
    """Write each land area's pieces per UN entity, and return one record per area."""
    land = [c for c in changes() if c["type"] in STEPS["land"]]
    conn.execute("CREATE TABLE land (change_id VARCHAR, code VARCHAR, name VARCHAR)")
    conn.executemany(
        "INSERT INTO land VALUES (?, ?, ?)",
        [(c["id"], c["entity"]["code"], c["entity"]["name"]) for c in land],
    )
    conn.execute(f"""--sql
        CREATE TABLE land_pieces AS
        SELECT * EXCLUDE (total) FROM (
            SELECT *, sum(km2) OVER (PARTITION BY change_id) AS total FROM (
                SELECT a.change_id, l.code, n.objectid AS un_objectid, n.un_iso3,
                       round({KM2.format("i.geometry")}, 3) AS km2, i.geometry
                FROM '{LAND}' a JOIN land l USING (change_id)
                JOIN '{data("01", "un_polygons")}' u
                  ON ST_Intersects(a.geometry, u.geometry)
                JOIN un n ON n.objectid = u.objectid,
                LATERAL (SELECT ST_Multi(ST_CollectionExtract(
                    ST_Intersection(a.geometry, u.geometry), 3)) AS geometry) i))
        WHERE km2 >= {MIN_LAND_SHARE} * total
    """)
    write_parquet(conn, "FROM land_pieces", Path(data("05", "land_areas")))
    records = []
    for c in land:
        rows = conn.execute(
            """--sql
            SELECT p.un_objectid, n.un_iso3, coalesce(n.un_name, n.un_iso3), p.km2,
                   ST_XMin(p.geometry), ST_YMin(p.geometry), ST_XMax(p.geometry),
                   ST_YMax(p.geometry)
            FROM land_pieces p JOIN un n ON n.objectid = p.un_objectid
            WHERE change_id = ? ORDER BY km2 DESC""",
            [c["id"]],
        ).fetchall()
        e = c["entity"]
        values = [
            dict(zip(("un_objectid", "un", "un_name", "km2"), r[:4], strict=True))
            | {"gaul": e["code"], "gaul_name": e["name"]}
            for r in rows
        ]
        box = [min(r[4] for r in rows), min(r[5] for r in rows)]
        box += [max(r[6] for r in rows), max(r[7] for r in rows)]
        km2 = round(sum(r[3] for r in rows), 3)
        records.append(
            c | {"km2": km2, "units": len(rows), "bbox": box, "values": values}
        )
    return records


def _labels(conn: DuckDBPyConnection) -> None:
    """Write a label point per polygon, or per change where names replace codes."""
    split = [c["id"] for c in changes() if c["type"] in STEPS["split"]]
    rows = conn.execute(f"""--sql
        SELECT p.c,
               CASE WHEN p.c LIKE 'S-%' OR list_contains({split}, p.c)
                    THEN concat(n.un_iso3, ' → ', a.iso3)
                    WHEN p.c = r.change_id THEN concat(n.un_iso3, ' → ', to_un.un_iso3)
                    WHEN r.change_id IS NOT NULL
                    THEN concat(to_un.un_iso3, ' → ', g.MAP_CODE)
                    WHEN p.entity IS NOT NULL THEN concat(n.un_iso3, ' → ', p.entity)
                    WHEN n.un_iso3 = g.MAP_CODE
                    THEN concat(coalesce(n.un_name, 'None'), ' → ', g.GAUL0_NAME)
                    ELSE concat(n.un_iso3, ' → ', g.MAP_CODE) END,
               round({KM2.format("p.part")}, 3),
               ST_X(ST_MaximumInscribedCircle(p.part).center),
               ST_Y(ST_MaximumInscribedCircle(p.part).center)
        FROM (SELECT t.c, t.unit_id, t.un_objectid, t.gaul_id, t.entity,
                     unnest(ST_Dump(t.geometry)).geom AS part
              FROM (SELECT unnest(change_ids) AS c, unit_id, un_objectid, gaul_id,
                           entity, geometry
                    FROM tagged) t) p
        JOIN un n ON n.objectid = p.un_objectid LEFT JOIN gaul g USING (gaul_id)
        JOIN unit_adm0 a USING (unit_id)
        LEFT JOIN relabels r USING (un_objectid, gaul_id)
        LEFT JOIN un to_un ON to_un.objectid = r.to_objectid
        QUALIFY n.un_iso3 IS DISTINCT FROM coalesce(p.entity, g.MAP_CODE)
             OR p.c LIKE 'S-%'
             OR row_number() OVER (
                 PARTITION BY p.c ORDER BY {KM2.format("p.part")} DESC) = 1
        UNION ALL
        SELECT change_id, concat(un_iso3, ' → ', cell_code), round(km2, 3),
               ST_X(ST_MaximumInscribedCircle(geometry).center),
               ST_Y(ST_MaximumInscribedCircle(geometry).center)
        FROM cell_islands
        UNION ALL
        SELECT change_id, concat(un_iso3, ' → ', code), km2,
               ST_X(ST_MaximumInscribedCircle(geometry).center),
               ST_Y(ST_MaximumInscribedCircle(geometry).center)
        FROM land_pieces
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
    _adm0(conn)
    write_parquet(
        conn,
        """--sql
        SELECT t.unit_id, t.un_objectid, t.un_owner, t.gaul_id, t.entity, t.area_id,
               a.adm0_id, a.iso3, t.parts,
               array_to_string(t.change_ids, ';') AS change_ids, t.geometry
        FROM tagged t JOIN unit_adm0 a USING (unit_id)""",
        Path(data("05", "units")),
    )
    _crosswalk(conn)
    island_errors = _island_errors(conn)
    write_parquet(
        conn,
        "SELECT change_id, km2, geometry FROM cell_islands",
        Path(data("05", "cell_islands")),
    )
    land = _land(conn)
    _labels(conn)
    records = [_record(c, conn) for c in changes() if c["type"] not in STEPS["land"]]
    splits = conn.execute("""--sql
        SELECT DISTINCT c FROM (SELECT unnest(change_ids) AS c FROM tagged)
        WHERE c LIKE 'S-%' ORDER BY c""").fetchall()
    records += [
        _record({"id": c, "type": "group_split", "keys": []}, conn) for (c,) in splits
    ]
    records += land
    records += island_errors + _lines(conn)
    out = stage_dir("05") / "changes.json"
    out.write_text(json.dumps(records, ensure_ascii=False, indent=1) + "\n")
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
            curated_dir / "changes.json",
            Path(data("01", "un_polygons")),
            Path(data("02", "un_parts")),
            OVERRIDES,
            LINKS,
            Path(data("01", "fieldmaps_voronoi")),
            Path(data("01", "line_overlaps")),
            DECISIONS,
            LAND,
        ],
    )
