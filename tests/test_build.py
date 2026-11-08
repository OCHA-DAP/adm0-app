"""Check the built build layer against the promises the crosswalk makes."""

import json

import pytest
from duckdb import DuckDBPyConnection, connect

from pipeline.build.common import build_dir, data, stage_dir

pytestmark = pytest.mark.skipif(
    not (build_dir / "06_export/checks.json").exists(),
    reason="run `python -m pipeline --step build` first",
)
VIET_NAM, SUDAN, HALAIB, DISPUTED = "281", 853, "133", "238"
DISPUTED_UNITS = 8
VIET_NAM_XMAX = 110
MIN_LINE_PATCHES = 8000


@pytest.fixture(scope="module")
def conn() -> DuckDBPyConnection:
    """Open a database with spatial loaded."""
    db = connect()
    db.execute("LOAD spatial")
    return db


def one(conn: DuckDBPyConnection, sql: str) -> object:
    """Return the first value of ``sql``."""
    return conn.execute(sql).fetchall()[0][0]


def test_checks_pass() -> None:
    """Every stage 06 check passed."""
    checks = json.loads((build_dir / "06_export/checks.json").read_text())
    assert all(c["passed"] for c in checks.values()), checks


def test_unit_ids_unique(conn: DuckDBPyConnection) -> None:
    """Each unit has its own id, and the crosswalk has one row per unit."""
    units = data("05", "units")
    crosswalk = data("05", "crosswalk")
    assert one(conn, f"SELECT count(*) - count(DISTINCT unit_id) FROM '{units}'") == 0
    assert (
        one(
            conn,
            f"""--sql
        SELECT count(*) FROM '{units}' u
        FULL JOIN '{crosswalk}' c USING (unit_id)
        WHERE u.un_objectid IS NULL OR c.un_objectid IS NULL""",
        )
        == 0
    )


def test_halaib_islands_follow_the_cut(conn: DuckDBPyConnection) -> None:
    """No Sudan island north of the line stays outside the Hala'ib entity."""
    parts = data("04", "parts")
    assert (
        one(
            conn,
            f"""--sql
        SELECT count(*) FROM '{parts}'
        WHERE un_objectid = {SUDAN} AND face = 0 AND ST_YMin(geometry) > 22.3
          AND gaul_id <> '{HALAIB}'""",
        )
        == 0
    )


def test_nearest_cell_does_not_change_an_island_owner(conn: DuckDBPyConnection) -> None:
    """South African islands GAUL lacks stay out of its French Southern Territories."""
    parts = data("04", "parts")
    sql = f"SELECT count(*) FROM '{parts}' WHERE un_iso3 = 'ZAF' AND gaul_id = '126'"
    assert one(conn, sql) == 0


def test_disputed_areas_stay_separate(conn: DuckDBPyConnection) -> None:
    """Each India-China area keeps one unit per UN entity."""
    units = data("05", "units")
    n = one(conn, f"SELECT count(*) FROM '{units}' WHERE gaul_id = '{DISPUTED}'")
    assert n == DISPUTED_UNITS


@pytest.mark.parametrize("name", ["path_errors", "path_disputed"])
def test_path_outputs_keep_the_build_area(conn: DuckDBPyConnection, name: str) -> None:
    """Each page step's output covers exactly the build's land."""
    area = "SELECT sum(ST_Area(geometry)) FROM '{}'"
    total = conn.execute(area.format(data("05", "units"))).fetchall()[0][0]
    state = conn.execute(area.format(data("06", name))).fetchall()[0][0]
    assert state == pytest.approx(total)


def test_viet_nam_has_no_south_china_sea_islands(conn: DuckDBPyConnection) -> None:
    """The Viet Nam export stops at the mainland coast and its near islands."""
    gaul = data("06", "gaul")
    assert (
        one(
            conn,
            f"""--sql
        SELECT ST_XMax(geometry) FROM '{gaul}' WHERE gaul_id = '{VIET_NAM}'""",
        )
        < VIET_NAM_XMAX
    )


def test_line_patches_cover_the_borders(conn: DuckDBPyConnection) -> None:
    """The GAUL and UN overlap still finds differences along the land borders."""
    patches = data("05", "line_patches")
    assert one(conn, f"SELECT count(*) FROM '{patches}'") > MIN_LINE_PATCHES


def test_review_decisions_apply() -> None:
    """Removed pairs are gone, and codes GAUL links to UN codes raise no row."""
    rows = json.loads((stage_dir("05") / "changes.json").read_text())
    ids = {r["id"] for r in rows}
    assert "E-xSR-PHL" not in ids
    assert not ids & {"E-xRI-XKI", "L-xKI-xRI"}
