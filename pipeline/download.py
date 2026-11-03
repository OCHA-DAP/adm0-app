"""Download every source into ``tmp/download/{source}/`` with a ``.date`` file."""

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from fnmatch import filter as fnfilter
from functools import partial
from logging import getLogger
from shutil import rmtree
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from httpx2 import Client, HTTPStatusError, Timeout, TransportError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from .config import download_dir

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = getLogger(__name__)

GAUL_URL = (
    "https://storage.googleapis.com/fao-maps-catalog-data/boundaries/GAUL_2025_L1.zip"
)
LAND_OSM_URL = (
    "https://osmdata.openstreetmap.de/download/land-polygons-complete-4326.zip"
)
LAND_WP_URL = "https://data.geodata.state.gov/WorldPolygons.zip"
LSIB_URL = "https://data.geodata.state.gov/LSIB.gpkg"
LSIB_META_URL = "https://geodata.state.gov/geonetwork/srv/api/records/3bdb81a0-c1b9-439a-a0b1-85dac30c59b2"
LSIB_NS = {
    "gco": "http://www.isotc211.org/2005/gco",
    "gmd": "http://www.isotc211.org/2005/gmd",
}
UNTERM_URL = "https://conferences.unite.un.org/untermapi/api/term/downloadCountries"
FIELDMAPS_LICENSE = "odbl"
FIELDMAPS_URL = "https://data.source.coop/fieldmaps/international/{license}/humanitarian/adm0-{geom}/adm0_{geom}.parquet"
M49_URL = "https://unstats.un.org/unsd/methodology/m49/overview/"


def _transient(e: BaseException) -> bool:
    """Retry network failures, rate limits and server errors, not 4xx."""
    if isinstance(e, HTTPStatusError):
        code = e.response.status_code
        return code == 429 or code >= 500  # noqa: PLR2004
    return isinstance(e, TransportError)


_retry = retry(
    retry=retry_if_exception(_transient),
    stop=stop_after_attempt(5),
    wait=wait_exponential(min=2, max=60),
    reraise=True,
)


def _client() -> Client:
    return Client(
        timeout=Timeout(60, connect=30),
        headers={"User-Agent": "Mozilla/5.0 (adm0-site)"},
        follow_redirects=True,
    )


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


@_retry
def _stream(url: str, dest: Path, *, required: bool = False) -> str:
    """Stream ``url`` to ``dest`` and return its Last-Modified date, else today.

    With ``required``, a missing Last-Modified header raises instead.
    """
    with _client() as client, client.stream("GET", url) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            f.writelines(r.iter_bytes(chunk_size=4 * 1024 * 1024))
        modified = r.headers.get("last-modified")
    if modified:
        return parsedate_to_datetime(modified).date().isoformat()
    if required:
        msg = f"{url}: date not found in Last-Modified header"
        raise ValueError(msg)
    return _today()


def _zip(
    url: str, out: Path, only: str | None = None, *, required: bool = False
) -> str:
    tmp = out / ".tmp"
    try:
        date = _stream(url, tmp, required=required)
        with ZipFile(tmp) as z:
            z.extractall(out, fnfilter(z.namelist(), only) if only else None)
    finally:
        tmp.unlink(missing_ok=True)
    return date


def _wp(out: Path) -> str:
    # The outer zip also ships a Deflate64 hash .txt that zipfile can't read.
    _zip(LAND_WP_URL, out, only="*WorldPolygon*.zip")
    inner = next(out.rglob("WorldPolygon*.zip"))
    with ZipFile(inner) as z:
        z.extractall(out)
    inner.unlink()
    gpkg = next(out.rglob("WorldPolygons*.gpkg"))
    match = re.search(r"_(\d{1,2}[A-Za-z]{3}\d{4})$", gpkg.parent.name)
    if match is None:
        msg = f"World Polygons date not found in folder name: {gpkg.parent.name}"
        raise ValueError(msg)
    return datetime.strptime(match[1], "%d%b%Y").replace(tzinfo=UTC).date().isoformat()


@_retry
def _lsib_date() -> str:
    with _client() as client:
        r = client.get(LSIB_META_URL, headers={"Accept": "application/xml"})
        r.raise_for_status()
    el = ET.fromstring(r.text).find(  # noqa: S314
        ".//gmd:CI_Citation/gmd:date/gmd:CI_Date/gmd:date/gco:Date", LSIB_NS
    )
    if el is None or el.text is None:
        msg = "LSIB date not found in metadata response"
        raise ValueError(msg)
    return el.text


def _lsib(out: Path) -> str:
    date = _lsib_date()
    _stream(LSIB_URL, out / "LSIB.gpkg")
    return date


def _ref(out: Path) -> str:
    _stream(UNTERM_URL, out / "unterm.xlsx")
    _stream(M49_URL, out / "m49.html")
    return _today()


def _fieldmaps(out: Path) -> str:
    dates = []
    for geom in ("polygons", "lines"):
        url = FIELDMAPS_URL.format(license=FIELDMAPS_LICENSE, geom=geom)
        dates.append(_stream(url, out / f"{geom}.parquet"))
    return max(dates)


def _fetch(source: str, fn: Callable[[Path], str]) -> None:
    out = download_dir / source
    rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    (out / ".date").write_text(fn(out))
    logger.info("%s: downloaded", source)


def main() -> None:
    """Download all sources in parallel."""
    jobs = {
        "gaul": partial(_zip, GAUL_URL),
        "lsib": _lsib,
        "osm": partial(_zip, LAND_OSM_URL, required=True),
        "wp": _wp,
        "ref": _ref,
        "fieldmaps": _fieldmaps,
    }
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = [pool.submit(_fetch, s, fn) for s, fn in jobs.items()]
    for f in futures:
        f.result()
