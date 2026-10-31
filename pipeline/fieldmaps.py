"""Build the fieldmaps LSIB humanitarian ADM0 (intl view)."""

from logging import getLogger
from typing import TYPE_CHECKING

from .config import (
    CRS,
    fieldmaps_dir,
    input_dir,
    open_db,
    prepare_dir,
    tmp_dir,
    write_parquet,
)

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

logger = getLogger(__name__)

SRC = input_dir / "fieldmaps"
GEOM_PRECISION = 0.000000001
LINE_KEYS = ["COUNTRY1", "COUNTRY2", "RANK", "LABEL"]


def _attributes(conn: DuckDBPyConnection) -> None:
    """Load the hand-curated point and line attributes."""
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE attrs_points AS
        SELECT * REPLACE (
            coalesce(iso_3_grp, iso_3) AS iso_3_grp,
            coalesce(region1_cd, status_cd) AS region1_cd,
            coalesce(region1_nm, status_nm) AS region1_nm,
            coalesce(region2_cd, region1_cd, status_cd) AS region2_cd,
            coalesce(region2_nm, region1_nm, status_nm) AS region2_nm,
            coalesce(region3_cd, region2_cd, region1_cd, status_cd) AS region3_cd,
            coalesce(region3_nm, region2_nm, region1_nm, status_nm) AS region3_nm
        )
        FROM read_csv('{SRC / "adm0_points.csv"}', all_varchar=true,
                      nullstr=['', '#N/A'])
    """)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE attrs_lines AS
        SELECT * EXCLUDE (rank_all)
        FROM read_csv('{SRC / "adm0_lines.csv"}', all_varchar=true,
                      nullstr=['', '#N/A'])
    """)


def _inputs(conn: DuckDBPyConnection) -> None:
    """Load land, template lines plus LSIB, and seed points."""
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE land_00 AS
        SELECT fid, geometry AS geom
        FROM read_parquet('{prepare_dir / "osm_land.parquet"}')
    """)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE lines_00 AS
        SELECT CC1, COUNTRY1, CC2, COUNTRY2, RANK::BIGINT AS RANK, LABEL, STATUS,
               NOTES, ST_SetCRS(geom, '{CRS}') AS geom
        FROM read_parquet('{SRC / "adm0_lines.parquet"}')
        UNION ALL
        SELECT l.CC1, COUNTRY1, l.CC2, COUNTRY2, l.RANK::BIGINT, LABEL, STATUS, NOTES,
               geometry
        FROM read_parquet('{prepare_dir / "lsib_lines.parquet"}') l
        -- Known erroneous LSIB segments.
        ANTI JOIN read_csv('{SRC / "lsib_drop.csv"}') d
          ON l.CC1 = d.CC1 AND l.CC2 = d.CC2 AND l.RANK::INTEGER = d.RANK
    """)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE points_00 AS
        SELECT id, ST_SetCRS(geom, '{CRS}') AS geom
        FROM read_parquet('{SRC / "adm0_points.parquet"}')
    """)


def _coverage_invalid(conn: DuckDBPyConnection, table: str) -> bool:
    return conn.execute(
        f'SELECT ST_CoverageInvalidEdges_Agg(geom) IS NOT NULL FROM "{table}"'
    ).fetchone()[0]


def _land_envelopes(conn: DuckDBPyConnection) -> list[tuple[int, bytes]]:
    """Each crossed land polygon's fid and envelope WKB."""
    return conn.execute(
        "SELECT fid, ST_AsWKB(ST_Envelope(geom)) FROM land_01"
    ).fetchall()


def _polygonize(conn: DuckDBPyConnection) -> None:
    """Polygonize the union of lines and seed each face from its point."""
    conn.execute("""--sql
        CREATE OR REPLACE TABLE lines_01 AS
        SELECT ST_Multi(ST_Union_Agg(geom)) AS geom FROM lines_00
    """)
    conn.execute("""--sql
        CREATE OR REPLACE TABLE voronoi_00 AS
        WITH faces AS (
            SELECT UNNEST(ST_Dump(ST_Polygonize(list(geom)))).geom AS geom
            FROM lines_01
        )
        SELECT p.id, f.geom
        FROM faces f JOIN points_00 p ON ST_DWithin(p.geom, f.geom, 0)
    """)
    faces, points = conn.execute("""--sql
        SELECT (SELECT count(*) FROM voronoi_00), (SELECT count(*) FROM points_00)
    """).fetchone()
    invalid = _coverage_invalid(conn, "voronoi_00")
    if faces != points or invalid:
        msg = f"polygonize: {faces} faces for {points} points, invalid={invalid}"
        raise RuntimeError(msg)


def _continents(conn: DuckDBPyConnection) -> None:
    """Keep the land masses crossed by a boundary line."""
    wkb = conn.execute("SELECT ST_AsWKB(geom) FROM lines_01").fetchone()[0]
    conn.execute(
        """--sql
        CREATE OR REPLACE TABLE land_01 AS
        SELECT * FROM land_00 WHERE ST_Intersects(geom, ST_GeomFromWKB($1))
        """,
        [wkb],
    )


def _intersection(conn: DuckDBPyConnection) -> None:
    """Clip voronoi cells to land; whole islands go to the cell holding them."""
    conn.execute("CREATE OR REPLACE TABLE clip (id VARCHAR, geom GEOMETRY)")
    # One land polygon per execute(), passed as WKB, caps GEOS memory.
    for fid, env in _land_envelopes(conn):
        cells = conn.execute(
            "SELECT id, ST_AsWKB(geom) FROM voronoi_00 "
            "WHERE ST_Intersects(geom, ST_GeomFromWKB($1))",
            [env],
        ).fetchall()
        for vid, cell in cells:
            conn.execute(
                """--sql
                INSERT INTO clip
                SELECT $1, ST_CollectionExtract(ST_Intersection(
                    (SELECT geom FROM land_01 WHERE fid = $2), ST_GeomFromWKB($3)
                ), 3)
                """,
                [vid, fid, cell],
            )
    conn.execute("""--sql
        CREATE OR REPLACE TABLE land_pts AS
        SELECT fid, ST_PointOnSurface(geom) AS pt FROM land_00
        WHERE fid NOT IN (SELECT fid FROM land_01)
    """)
    for vid, cell in conn.execute(
        "SELECT id, ST_AsWKB(geom) FROM voronoi_00"
    ).fetchall():
        conn.execute(
            """--sql
            INSERT INTO clip
            SELECT $1, l.geom FROM land_pts p JOIN land_00 l USING (fid)
            WHERE ST_Contains(ST_GeomFromWKB($2), p.pt)
            """,
            [vid, cell],
        )
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE polygons_00 AS
        SELECT id, ST_Multi(ST_ReducePrecision(ST_Union_Agg(geom), {GEOM_PRECISION}))
            AS geom
        FROM clip WHERE NOT ST_IsEmpty(geom) GROUP BY id
    """)


def _dissolve(conn: DuckDBPyConnection, src: str, out: str) -> None:
    """Dissolve cells onto their intl-view ``a_intl`` unit and join attributes."""
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{out}" AS
        WITH dissolved AS (
            SELECT coalesce(a.a_intl, s.id) AS id,
                   ST_Multi(ST_Union_Agg(s.geom)) AS geom
            FROM "{src}" s JOIN attrs_points a USING (id)
            GROUP BY ALL
        )
        SELECT a.* EXCLUDE (a_intl, p_intl, a_all, p_all), d.geom
        FROM dissolved d LEFT JOIN attrs_points a USING (id)
    """)


def _lines(conn: DuckDBPyConnection) -> None:
    """Clip boundary lines to the crossed land masses, intl ranks applied."""
    keys = ", ".join(f'"{k}"' for k in LINE_KEYS)
    conn.execute(
        f"CREATE OR REPLACE TABLE lines_clip AS "
        f"SELECT {keys}, geom FROM lines_00 LIMIT 0"
    )
    for fid, env in _land_envelopes(conn):
        land = conn.execute(
            "SELECT ST_AsWKB(geom) FROM land_01 WHERE fid = $1", [fid]
        ).fetchone()[0]
        for *vals, line in conn.execute(
            f"SELECT {keys}, ST_AsWKB(geom) FROM lines_00 "
            "WHERE ST_Intersects(ST_Envelope(geom), ST_GeomFromWKB($1))",
            [env],
        ).fetchall():
            conn.execute(
                """--sql
                INSERT INTO lines_clip SELECT $1, $2, $3, $4, ST_CollectionExtract(
                    ST_Intersection(ST_GeomFromWKB($5), ST_GeomFromWKB($6)), 2)
                """,
                [*vals, line, land],
            )
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE lines_02 AS
        WITH dissolved AS (
            SELECT {keys}, ST_Multi(ST_ReducePrecision(
                ST_Union_Agg(geom), {GEOM_PRECISION})) AS geom
            FROM lines_clip WHERE NOT ST_IsEmpty(geom) GROUP BY ALL
        )
        SELECT a.adm_id, a.cc1, d."COUNTRY1" AS country1, a.cc2,
               d."COUNTRY2" AS country2,
               coalesce(a.rank_intl::BIGINT, d."RANK") AS rank,
               d."LABEL" AS label, a.status, a.notes, d.geom
        FROM dissolved d LEFT JOIN attrs_lines a
          ON d."COUNTRY1" = a.country1 AND d."COUNTRY2" = a.country2
         AND d."RANK" = a.rank::BIGINT AND d."LABEL" IS NOT DISTINCT FROM a.label
        WHERE coalesce(a.rank_intl::BIGINT, d."RANK") > 0
    """)


def _write(conn: DuckDBPyConnection) -> None:
    for table, name in (
        ("polygons_01", "polygons"),
        ("voronoi_01", "voronoi"),
        ("lines_02", "lines"),
    ):
        write_parquet(
            conn,
            f'SELECT * EXCLUDE geom, geom AS geometry FROM "{table}"',
            fieldmaps_dir / f"{name}.parquet",
        )


def _validate(conn: DuckDBPyConnection) -> None:
    def count(sql: str) -> int:
        return conn.execute(sql).fetchone()[0]

    invalid = "WHERE geom IS NULL OR NOT ST_IsValid(geom)"
    issues = []
    if bad := count(f"SELECT count(*) FROM polygons_01 {invalid}"):
        issues.append(f"polygons_01: {bad} null/invalid geometries")
    if dup := count("SELECT count(*) - count(DISTINCT id) FROM polygons_01"):
        issues.append(f"polygons_01: {dup} duplicate id")
    if bad := count(f"SELECT count(*) FROM lines_02 {invalid}"):
        issues.append(f"lines_02: {bad} null/invalid geometries")
    if _coverage_invalid(conn, "polygons_01"):
        issues.append("polygons_01: overlaps or gaps between units")
    if issues:
        msg = "; ".join(issues)
        raise RuntimeError(msg)


def main() -> None:
    """Build polygons, voronoi cells and lines."""
    fieldmaps_dir.mkdir(parents=True, exist_ok=True)
    conn = open_db(tmp_dir / "fieldmaps.duckdb")
    _attributes(conn)
    _inputs(conn)
    _polygonize(conn)
    _continents(conn)
    _intersection(conn)
    _dissolve(conn, "polygons_00", "polygons_01")
    _dissolve(conn, "voronoi_00", "voronoi_01")
    _lines(conn)
    _validate(conn)
    _write(conn)
    conn.close()
    logger.info("fieldmaps built")
