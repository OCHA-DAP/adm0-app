"""Name each ADM0 row and correct its attributes from the UN reference."""

from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING

from pipeline.config import prepare_dir, write_parquet

from .common import (
    changes,
    connect,
    curated_dir,
    data,
    finish,
    unchanged,
)

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

logger = getLogger(__name__)

REF = prepare_dir / "ref.parquet"
OVERRIDES = curated_dir / "name_overrides.csv"
COAST_OVERRIDES = curated_dir / "coast_overrides.csv"
FIELDS = ("name", "map_label", "status")


def _tables(conn: DuckDBPyConnection) -> None:
    """Name each row from its FieldMaps piece and the UN reference."""
    conn.execute("CREATE TABLE entities (code VARCHAR, name VARCHAR)")
    conn.executemany(
        "INSERT INTO entities VALUES (?, ?)",
        [(e["code"], e["name"]) for c in changes() if (e := c.get("entity"))],
    )
    fieldmaps = data("01", "fieldmaps_voronoi")
    conn.execute(f"""--sql
        INSERT INTO entities
        SELECT DISTINCT unit_id, name FROM read_csv('{COAST_OVERRIDES}')
        WHERE name IS NOT NULL;
        CREATE TABLE pieces AS
        SELECT DISTINCT u.adm0_id, p.piece
        FROM '{data("04", "parts")}' p JOIN '{data("05", "units")}' u
          ON u.unit_id = substr(md5(concat_ws(
              '|', p.un_objectid, p.gaul_id, p.area_id, p.piece)), 1, 12)
        WHERE p.piece IS NOT NULL;
        CREATE TABLE fm AS
        SELECT DISTINCT adm0_id AS piece, iso_3, adm0_name, adm0_name1, status_nm
        FROM '{fieldmaps}';
        CREATE TABLE fm_code AS
        SELECT iso_3, any_value(adm0_name) AS adm0_name,
               any_value(adm0_name1) AS adm0_name1, any_value(status_nm) AS status_nm
        FROM fm GROUP BY 1 HAVING count(*) = 1;
        CREATE TABLE named AS
        SELECT * EXCLUDE fm_label, coalesce(fm_label, name) AS map_label FROM (
        SELECT a.*, coalesce(f.adm0_name, c.adm0_name) AS fm_label,
               CASE WHEN p.piece IS NOT NULL
                    THEN regexp_replace(f.adm0_name, ' \\([A-Z]{{2}}\\)$', '')
                    ELSE coalesce(nullif(r.name_m49, ''), c.adm0_name1,
                                  e.name, g.GAUL0_NAME) END AS name,
               CASE WHEN a.iso3 = u.iso3cd THEN u.status_label
                    ELSE coalesce(f.status_nm, c.status_nm,
                                  CASE WHEN a.iso3 LIKE 'X%' THEN 'Undetermined' END)
                    END AS status
        FROM '{data("08", "adm0")}' a
        LEFT JOIN pieces p USING (adm0_id)
        LEFT JOIN fm f ON f.piece = p.piece
        LEFT JOIN fm_code c ON c.iso_3 = a.iso3
        LEFT JOIN '{REF}' r ON r.iso3 = a.iso3
        LEFT JOIN '{data("01", "un_polygons")}' u ON u.objectid::VARCHAR = a.un_objectid
        LEFT JOIN '{data("01", "gaul_polygons")}' g USING (gaul_id)
        LEFT JOIN (SELECT code, any_value(name) AS name FROM entities GROUP BY 1) e
          ON e.code = a.iso3);
    """)
    for field in FIELDS:
        conn.execute(f"""--sql
            UPDATE named n SET {field} = o.value
            FROM read_csv('{OVERRIDES}', all_varchar = true) o
            WHERE o.adm0_id = n.adm0_id AND o.field = '{field}'
        """)


def main() -> None:
    """Write the named ADM0 output."""
    inputs = [
        Path(__file__),
        Path(data("08", "adm0")),
        Path(data("04", "parts")),
        Path(data("05", "units")),
        Path(data("01", "fieldmaps_voronoi")),
        Path(data("01", "un_polygons")),
        Path(data("01", "gaul_polygons")),
        REF,
        OVERRIDES,
        COAST_OVERRIDES,
        curated_dir / "changes.json",
    ]
    if all(unchanged("09", p) for p in inputs):
        logger.info("stage 09: inputs unchanged")
        return
    conn = connect()
    _tables(conn)
    write_parquet(
        conn,
        """--sql
        SELECT adm0_id, iso3, name, map_label, status, un_iso3, un_objectid,
               gaul_id, gaul_code, geometry
        FROM named ORDER BY adm0_id""",
        Path(data("09", "adm0")),
    )
    finish(conn, "09", inputs)
