"""Join every source's ADM0 attributes on ISO3 into ``attributes.json`` for the site."""

from logging import getLogger

from .config import SOURCE_COLUMNS, open_db, prepare_dir, tiles_dir

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
