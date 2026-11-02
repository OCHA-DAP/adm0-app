"""Join every source's ADM0 attributes on ISO3 into ``attributes.json`` for the site."""

from logging import getLogger
from typing import TYPE_CHECKING

from .config import SOURCE_COLUMNS, layers, open_db, prepare_dir, tiles_dir

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

logger = getLogger(__name__)

# Map polygon layers, keyed by source; their code and name match the tiles.
POLYGONS = {lyr["source"]: lyr for lyr in layers() if lyr["kind"] == "polygon"}
# Prepared table each source's attributes come from.
TABLES = {s: lyr["id"] for s, lyr in POLYGONS.items()} | {"unterm": "ref", "m49": "ref"}

# Boxes wider than a hemisphere shift western parts east by 360 when that gives
# the narrower box, so east can pass 180.
BBOX = """CASE WHEN max(x1) - min(x0) <= greatest(180, max(e1) - min(e0))
    THEN [min(x0), min(y0), max(x1), max(y1)]
    ELSE [min(e0), min(y0), max(e1), max(y1)] END"""


def _parts(conn: DuckDBPyConnection) -> None:
    """Load every polygon of every geometry source's features into ``parts``."""
    features = " UNION ALL ".join(
        f"""SELECT upper({lyr["code"]}) AS iso3, '{s}' AS source,
            '{lyr["id"]}' AS layer, {rank} AS rank, row_number() OVER () AS fid,
            {lyr["name"]} AS name,
            coalesce(nullif(trim({lyr["name"]}::VARCHAR), ''),
                {SOURCE_COLUMNS[s]["name"]}) AS label,
            geometry
        FROM read_parquet('{prepare_dir / lyr["id"]}.parquet')"""
        for rank, (s, lyr) in enumerate(POLYGONS.items())
    )
    conn.execute(f"""--sql
        CREATE TABLE parts AS
        SELECT *, CASE WHEN x1 <= 0 THEN x0 + 360 ELSE x0 END AS e0,
               CASE WHEN x1 <= 0 THEN x1 + 360 ELSE x1 END AS e1
        FROM (SELECT iso3, source, layer, rank, fid, trim(name::VARCHAR) AS name,
                trim(label::VARCHAR) AS label, ST_Area(part) AS area,
                round(ST_XMin(part), 3) AS x0, round(ST_XMax(part), 3) AS x1,
                round(ST_YMin(part), 3) AS y0, round(ST_YMax(part), 3) AS y1
            FROM (SELECT * EXCLUDE geometry, unnest(ST_Dump(geometry)).geom AS part
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
            if col not in {"id", "code", "entity"}
        )
        count = f"count(*) AS count_{source}," if source in POLYGONS else ""
        selects.append(
            f"""(SELECT upper({cols["code"]}) AS iso3, {count}
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
