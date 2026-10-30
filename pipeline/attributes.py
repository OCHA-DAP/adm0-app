"""Join every source's ADM0 attributes on ISO3 into ``attributes.json`` for the site."""

from logging import getLogger
from typing import TYPE_CHECKING

from .config import SOURCE_COLUMNS, open_db, prepare_dir, tiles_dir

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

logger = getLogger(__name__)

# Prepared table each source's attributes come from.
TABLES = {
    "gaul": "gaul_l0",
    "ungeodata": "ungeodata_polygons",
    "fieldmaps": "fieldmaps_polygons",
    "wp": "wp_polygons",
    "unterm": "ref",
    "m49": "ref",
}
GEOMETRY = ["gaul", "ungeodata", "fieldmaps", "wp"]

# Boxes wider than a hemisphere shift western parts east by 360 when that gives
# the narrower box, so east can pass 180.
BBOX = """CASE WHEN max(x1) - min(x0) <= greatest(180, max(e1) - min(e0))
    THEN [min(x0), min(y0), max(x1), max(y1)]
    ELSE [min(e0), min(y0), max(e1), max(y1)] END"""


def _parts(conn: DuckDBPyConnection) -> None:
    """Load every polygon of every geometry source's features into ``parts``."""
    features = " UNION ALL ".join(
        f"""SELECT upper({c["code"]}) AS iso3, '{s}' AS source, '{TABLES[s]}' AS layer,
            {rank} AS rank,
            row_number() OVER () AS fid, {c.get("mapname", c["name"])} AS name,
            coalesce(nullif(trim({c.get("mapname", c["name"])}::VARCHAR), ''),
                {c["name"]}) AS label,
            geometry
        FROM read_parquet('{prepare_dir / TABLES[s]}.parquet')"""
        for rank, s in enumerate(GEOMETRY)
        for c in [SOURCE_COLUMNS[s]]
    )
    conn.execute(f"""--sql
        CREATE TABLE parts AS
        SELECT *, CASE WHEN x1 <= 0 THEN x0 + 360 ELSE x0 END AS e0,
               CASE WHEN x1 <= 0 THEN x1 + 360 ELSE x1 END AS e1
        FROM (SELECT iso3, source, layer, rank, fid, trim(name::VARCHAR) AS name,
                trim(label::VARCHAR) AS label,
                geometry, ST_Area(geometry) AS area,
                round(ST_XMin(geometry), 3) AS x0, round(ST_XMax(geometry), 3) AS x1,
                round(ST_YMin(geometry), 3) AS y0, round(ST_YMax(geometry), 3) AS y1
            FROM (SELECT * EXCLUDE geometry, unnest(ST_Dump(geometry)).geom AS geometry
                FROM ({features}) WHERE iso3 IS NOT NULL))
    """)


def _features(conn: DuckDBPyConnection) -> None:
    """Group parts into features with their area and bbox."""
    conn.execute(f"""--sql
        CREATE TABLE features AS
        SELECT iso3, source, layer, fid, source || ':' || fid AS id,
               any_value(rank) AS rank, any_value(name) AS name,
               any_value(label) AS label,
               sum(area) AS area, {BBOX} AS bbox
        FROM parts GROUP BY 1, 2, 3, 4
    """)


def main() -> None:
    """Write one row per ISO3 code with each source's values side by side."""
    conn = open_db()
    selects = []
    for source, table in TABLES.items():
        cols = SOURCE_COLUMNS[source]
        aggs = ", ".join(
            f"string_agg(DISTINCT trim({expr}::VARCHAR), ' | ' ORDER BY "
            f"trim({expr}::VARCHAR)) AS {col}_{source}"
            for col, expr in cols.items()
            if col not in {"id", "code"}
        )
        selects.append(
            f"""(SELECT upper({cols["code"]}) AS iso3, count(*) AS count_{source},
            {aggs}
            FROM read_parquet('{prepare_dir / table}.parquet')
            WHERE {cols["code"]} IS NOT NULL GROUP BY 1) AS {source}"""
        )
    _parts(conn)
    selects.append(f"(SELECT iso3, {BBOX} AS bbox FROM parts GROUP BY 1) AS extent")
    _features(conn)
    selects.append(
        """(SELECT iso3, list(
                {s: source, id: id, layer: layer, name: name, label: label, bbox: bbox}
                ORDER BY rank, area DESC) AS parts
        FROM features GROUP BY 1) AS features"""
    )
    query = "SELECT * FROM " + " FULL JOIN ".join(
        [selects[0], *(f"{s} USING (iso3)" for s in selects[1:])]
    )
    tiles_dir.mkdir(parents=True, exist_ok=True)
    out = tiles_dir / "attributes.json"
    conn.execute(f"""--sql
        COPY ({query} ORDER BY iso3) TO '{out}' (FORMAT JSON, ARRAY true)
    """)
    n = conn.execute(f"SELECT count(*) FROM read_json('{out}')").fetchone()[0]
    logger.info("attributes: %d rows", n)
