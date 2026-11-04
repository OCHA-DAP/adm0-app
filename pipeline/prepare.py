"""Normalize downloaded sources into GeoParquet under ``tmp/prepare/``."""

import html
import re
from logging import getLogger
from typing import TYPE_CHECKING

from .config import download_dir, input_dir, open_db, prepare_dir, write_parquet

if TYPE_CHECKING:
    from pathlib import Path

    from duckdb import DuckDBPyConnection

logger = getLogger(__name__)

UNTERM_LANGS = ("English", "French", "Spanish", "Russian", "Chinese", "Arabic")
UNTERM_STATUS = {
    0: "Member State",
    1: "Observer State",
    2: "Member of specialized agencies",
}
UNGEODATA_STATUS = {
    0: "Antarctica",
    1: "State",
    2: "Occupied Palestinian Territory",
    3: "Non-Self-Governing Territory",
    4: "Territory",
    5: "Special Region or Province",
    99: "Undetermined",
}
# Line types from the UN Guidelines for the Publication of Maps, as line_type.
UNGEODATA_LINE_TYPE = {
    2: "special",
    3: "armistice",
    4: "separation",
    8: "autonomous",
    9: "sovereign",
}
LSIB_LINE_TYPE = """CASE WHEN label LIKE '%Line of Control%' THEN 'separation'
    WHEN status = 'Special Line' THEN 'special'
    WHEN status = 'Other Line of International Separation' THEN 'armistice'
    ELSE 'international' END AS line_type"""


def _copy(conn: DuckDBPyConnection, query: str, name: str) -> None:
    write_parquet(conn, query, prepare_dir / f"{name}.parquet")


def _strip_stars(s: str) -> str:
    return re.sub(r"\s*\*+$", "", s)


def gaul(conn: DuckDBPyConnection) -> None:
    """Dissolve GAUL 2025 L1 to one L0 entity per distinct L0 attribute set."""
    path = download_dir / "gaul/gaul_2025_l1.shp"
    conn.execute(f"CREATE TABLE gaul_l1 AS SELECT * FROM ST_Read('{path}')")
    attrs = "GAUL0_CODE, ISO3_CODE, MAP_CODE, GAUL0_NAME, CONTINENT"
    for code, names in conn.execute(f"""--sql
        SELECT GAUL0_CODE, list(DISTINCT GAUL0_NAME) FROM gaul_l1
        GROUP BY GAUL0_CODE HAVING count(DISTINCT ({attrs})) > 1
    """).fetchall():
        logger.warning("GAUL0_CODE %d splits into %s", code, names)
    # gaul_id stays the L0 code unless that code carries several attribute sets.
    _copy(
        conn,
        f"""--sql
        SELECT CASE WHEN count(*) OVER (PARTITION BY GAUL0_CODE) = 1
                    THEN GAUL0_CODE::VARCHAR
                    ELSE GAUL0_CODE || '-' || ISO3_CODE || '-' || row_number()
                         OVER (PARTITION BY GAUL0_CODE ORDER BY GAUL0_NAME)
               END AS gaul_id,
               * EXCLUDE geometry, geometry
        FROM (
            SELECT {attrs},
                   ST_Multi(ST_CollectionExtract(
                       ST_MakeValid(ST_Union_Agg(geom)), 3)) AS geometry
            FROM gaul_l1 GROUP BY ALL
        )
        ORDER BY GAUL0_CODE, gaul_id
        """,
        "gaul_l0",
    )


def _shared_lines(
    conn: DuckDBPyConnection, source: str, polygons: str, code: str, name: str
) -> None:
    """Derive ``source``'s boundary lines from edges its neighbouring polygons share."""
    path = prepare_dir / f"{polygons}.parquet"
    sid = f"{source}_id"
    conn.execute(f"""--sql
        CREATE OR REPLACE TEMP TABLE boundary AS
        SELECT {sid} AS id, {code} AS code, {name} AS name,
               ST_Boundary(geometry) AS boundary,
               ST_XMin(geometry) AS xmin, ST_YMin(geometry) AS ymin,
               ST_XMax(geometry) AS xmax, ST_YMax(geometry) AS ymax
        FROM read_parquet('{path}')
    """)
    conn.execute("""--sql
        CREATE OR REPLACE TEMP TABLE pairs AS
        SELECT a.id AS id_1, b.id AS id_2
        FROM boundary a JOIN boundary b ON a.id < b.id
         AND a.xmin <= b.xmax AND b.xmin <= a.xmax
         AND a.ymin <= b.ymax AND b.ymin <= a.ymax
    """)
    _copy(
        conn,
        f"""--sql
        SELECT * FROM (
            SELECT a.id AS {sid}_1, a.code AS iso3_1, a.name AS name_1,
                   b.id AS {sid}_2, b.code AS iso3_2, b.name AS name_2,
                   ST_LineMerge(ST_CollectionExtract(
                       ST_Intersection(a.boundary, b.boundary), 2)) AS geometry
            FROM pairs p
            JOIN boundary a ON a.id = p.id_1
            JOIN boundary b ON b.id = p.id_2
        )
        WHERE NOT ST_IsEmpty(geometry)
        ORDER BY {sid}_1, {sid}_2
        """,
        f"{source}_lines",
    )


def gaul_lines(conn: DuckDBPyConnection) -> None:
    """Derive GAUL L0 boundary lines."""
    _shared_lines(conn, "gaul", "gaul_l0", "ISO3_CODE", "GAUL0_NAME")


def wb(conn: DuckDBPyConnection) -> None:
    """Copy World Bank ADM0 polygons, NDLSA included, and derive their lines."""
    path = download_dir / "wb/adm0_all_layers.parquet"
    # NDLSA rows have no ADM0CD_c, and Jammu and Kashmir appears once per sovereign.
    _copy(
        conn,
        f"""--sql
        SELECT coalesce(ADM0CD_c, NAM_0 || coalesce('-' || SOV_ISO_A3, '')) AS wb_id,
               * EXCLUDE geometry, geometry
        FROM (SELECT * REPLACE (regexp_replace(NAM_0, '^\\s+|\\s+$', '', 'g') AS NAM_0)
              FROM read_parquet('{path}'))
        ORDER BY wb_id
        """,
        "wb_polygons",
    )
    _shared_lines(conn, "wb", "wb_polygons", "ISO_A3", "NAM_0")


def _gpkg(
    conn: DuckDBPyConnection, path: Path, where: str, name: str, extra: str = ""
) -> None:
    """Copy the one GeoPackage layer whose name matches ``where``, plus ``extra``."""
    layer = conn.execute(f"""--sql
        SELECT name FROM (
            SELECT UNNEST(layers).name AS name FROM ST_Read_Meta('{path}')
        )
        WHERE {where}
    """).fetchone()[0]
    _copy(
        conn,
        f"""--sql
        SELECT * EXCLUDE (fid, geom){extra}, geom AS geometry
        FROM ST_Read('{path}', layer='{layer}')
        """,
        name,
    )


def lsib(conn: DuckDBPyConnection) -> None:
    """Copy LSIB boundary lines."""
    path = download_dir / "lsib/LSIB.gpkg"
    where = "starts_with(name, 'Department of State LSIB')"
    _gpkg(conn, path, where, "lsib_lines", f", {LSIB_LINE_TYPE}")


def wp(conn: DuckDBPyConnection) -> None:
    """Copy State Department World Polygons (full resolution layer)."""
    path = next((download_dir / "wp").rglob("WorldPolygons*.gpkg"))
    _gpkg(conn, path, "regexp_full_match(name, 'DoS_WP_\\d+_\\d+')", "wp_polygons")


def osm(conn: DuckDBPyConnection) -> None:
    """Copy OSM land polygons."""
    path = next((download_dir / "osm").rglob("land_polygons.shp"))
    _copy(
        conn,
        f"SELECT row_number() OVER () AS fid, geom AS geometry FROM ST_Read('{path}')",
        "osm_land",
    )


def _key(name: str) -> str:
    """Match UNTERM names ("Sudan (the)", "Côte d'Ivoire") to M49 names."""
    name = _strip_stars(name.strip())
    name = re.sub(r"\s*\((the|The)\)$", "", name)
    return name.replace("\N{RIGHT SINGLE QUOTATION MARK}", "'").strip().lower()


M49_COLUMNS = (
    "Region Name",
    "Sub-region Name",
    "Intermediate Region Name",
    "Country or Area",
    "M49 Code",
    "ISO-alpha2 Code",
    "ISO-alpha3 Code",
)


def _m49_rows() -> list[dict[str, str]]:
    """Rows of the UNSD M49 overview table, keyed by its header names."""
    page = (download_dir / "ref/m49.html").read_text(encoding="utf-8")
    start = page.find('id="ENG_Overview"')
    if start < 0:
        msg = "M49 page has no ENG_Overview table"
        raise ValueError(msg)
    table = re.sub(
        r"<!--.*?-->", "", page[start : page.find("</table>", start)], flags=re.DOTALL
    )
    head, *body = [
        [
            html.unescape(re.sub("<[^>]+>", "", td)).strip()
            for td in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
        ]
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.DOTALL)
    ]
    if missing := [c for c in M49_COLUMNS if c not in head]:
        msg = f"M49 table lacks columns: {missing}"
        raise ValueError(msg)
    rows = [
        dict(zip(head, cells, strict=True)) for cells in body if len(cells) == len(head)
    ]
    return [r for r in rows if r["M49 Code"].isdigit()]


def ref(conn: DuckDBPyConnection) -> None:
    """Join UNTERM names to M49 codes and regions, one row per M49 area."""
    conn.execute("INSTALL excel; LOAD excel")
    unterm = conn.execute(f"""--sql
        SELECT * FROM read_xlsx('{download_dir / "ref/unterm.xlsx"}', all_varchar=true)
        WHERE "English short" IS NOT NULL
    """).fetchall()
    cols = [d[0].strip() for d in conn.description]
    by_key = {
        _key(r[cols.index("English short")]): dict(zip(cols, r, strict=True))
        for r in unterm
    }
    out, used = [], set()
    for m in _m49_rows():
        u = by_key.get(_key(m["Country or Area"]))
        if u:
            used.add(_key(m["Country or Area"]))
        short = u["English short"] if u else ""
        stars = len(short.strip()) - len(short.strip().rstrip("*"))
        clean = {k: _strip_stars((v or "").strip()) for k, v in (u or {}).items()}
        out.append(
            {
                "iso3": m["ISO-alpha3 Code"],
                "iso2": m["ISO-alpha2 Code"],
                "m49": m["M49 Code"],
                "name_m49": m["Country or Area"],
                "un_status": UNTERM_STATUS[stars] if u else "Other area",
                **{
                    f"name_{lang[:2].lower()}_{form}": clean.get(f"{lang} {form}", "")
                    for lang in UNTERM_LANGS
                    for form in ("short", "formal")
                },
                "region": m["Region Name"],
                "subregion": m["Sub-region Name"],
                "intermediate_region": m["Intermediate Region Name"],
            }
        )
    missing = sorted(set(by_key) - used)
    if missing:
        msg = f"UNTERM names with no M49 match: {missing}"
        raise ValueError(msg)
    conn.execute(
        "CREATE TABLE ref (" + ", ".join(f'"{c}" VARCHAR' for c in out[0]) + ")"
    )
    conn.executemany(
        f"INSERT INTO ref VALUES ({', '.join('?' * len(out[0]))})",
        [list(r.values()) for r in out],
    )
    write_parquet(
        conn, "SELECT * FROM ref ORDER BY iso3", prepare_dir / "ref.parquet", geo=False
    )


def ungeodata(conn: DuckDBPyConnection) -> None:
    """Copy UN Geodata 1M country polygons and international lines from ``inputs/``."""
    status = " ".join(f"WHEN {k} THEN '{v}'" for k, v in UNGEODATA_STATUS.items())
    line_type = " ".join(f"WHEN {k} THEN '{v}'" for k, v in UNGEODATA_LINE_TYPE.items())
    # bdytyp 0 is coastline, 6 and 7 subnational, 99 other.
    for layer, name, extra, where in (
        (
            "bnda_cty",
            "ungeodata_polygons",
            f", CASE stscod {status} END AS status_label",
            "true",
        ),
        (
            "bndl",
            "ungeodata_lines",
            f", CASE bdytyp {line_type} ELSE 'international' END AS line_type",
            "bdytyp IN (1, 2, 3, 4, 8, 9)",
        ),
    ):
        path = input_dir / f"ungeodata/{layer}.parquet"
        if not path.exists():
            msg = f"{path} missing; import it from the UN Geodata 1M FileGDB"
            raise FileNotFoundError(msg)
        _copy(
            conn,
            f"SELECT * EXCLUDE globalid{extra} "
            f"FROM read_parquet('{path}') WHERE {where}",
            name,
        )


def fieldmaps(conn: DuckDBPyConnection) -> None:
    """Copy the published fieldmaps humanitarian polygons and lines."""
    for path in sorted((download_dir / "fieldmaps").glob("*.parquet")):
        # Published lines are two-point segments, which tiling drops at low zoom.
        lines = path.stem == "lines"
        merge = (
            " REPLACE (ST_Multi(ST_LineMerge(geometry)) AS geometry)" if lines else ""
        )
        line_type = f", {LSIB_LINE_TYPE}" if lines else ""
        _copy(
            conn,
            f"SELECT *{merge}{line_type} FROM read_parquet('{path}')",
            f"fieldmaps_{path.stem}",
        )


def main() -> None:
    """Prepare every downloaded source."""
    prepare_dir.mkdir(parents=True, exist_ok=True)
    conn = open_db()
    for fn in (ref, gaul, gaul_lines, lsib, wp, osm, ungeodata, fieldmaps, wb):
        fn(conn)
