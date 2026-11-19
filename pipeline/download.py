"""Download every source into ``tmp/download/{source}/`` with a ``.date`` file."""

import json
import re
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from fnmatch import filter as fnfilter
from functools import partial
from logging import getLogger
from os import getenv
from shutil import rmtree
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from dotenv import load_dotenv
from httpx2 import Client, HTTPStatusError, Timeout, TransportError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from .config import download_dir, root

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
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Scarborough Shoal and Minerva Reefs: mapped as reefs, so absent from OSM land.
OSM_REEFS = {"way": (43145194, 43145209), "relation": (18554868,)}
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
UNGEODATA_URL = "https://pro-ags2.dfs.un.org/arcgis/rest/services/Hosted/UNgeodata_1Million/FeatureServer"
UNGEODATA_ITEM_URL = "https://geoportal.un.org/arcgis/sharing/rest/content/items/52bf5f875877459dae265c8cff69338f"
# Output name: (layer id, page size). Country polygons are large, so small pages.
UNGEODATA_LAYERS = {"bnda_cty": (4, 10), "bndl": (1, 2000)}
WB_URL = (
    "https://datacatalogfiles.worldbank.org/ddh-published/0038272/3/DR0096331/"
    "World%20Bank%20Official%20Boundaries%20%28Parquet%29/"
    "World%20Bank%20Official%20Boundaries%20-%20Admin%200_all_layers.parquet"
)


class AgsError(ValueError):
    """An error ArcGIS reports in a 200 body, with its code."""

    def __init__(self, msg: str, code: int | None) -> None:
        """Keep the ArcGIS error code for the retry check."""
        super().__init__(msg)
        self.code = code


def _transient(e: BaseException) -> bool:
    """Retry network failures, rate limits and server errors, not 4xx."""
    if isinstance(e, HTTPStatusError):
        code = e.response.status_code
    elif isinstance(e, AgsError):
        code = e.code or 0
    else:
        return isinstance(e, TransportError)
    return code == 429 or code >= 500  # noqa: PLR2004


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


@_retry
def _reefs(out: Path) -> None:
    """Write the ``OSM_REEFS`` features with their geometry to ``reefs.json``."""
    ids = "".join(f"{t}(id:{','.join(map(str, v))});" for t, v in OSM_REEFS.items())
    with _client() as client:
        r = client.post(
            OVERPASS_URL,
            data={"data": f"[out:json][timeout:60];({ids});out geom;"},
            timeout=Timeout(120, connect=30),
            # Overpass answers 406 to browser-like user agents.
            headers={"User-Agent": "adm0-site"},
        )
        r.raise_for_status()
    found = {(e["type"], e["id"]) for e in r.json()["elements"]}
    expected = {(t, i) for t, v in OSM_REEFS.items() for i in v}
    if found != expected:
        msg = f"Overpass reefs missing: {sorted(expected - found)}"
        raise ValueError(msg)
    (out / "reefs.json").write_text(r.text)


def _osm(out: Path) -> str:
    date = _zip(LAND_OSM_URL, out, required=True)
    _reefs(out)
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


def _wb(out: Path) -> str:
    return _stream(WB_URL, out / "adm0_all_layers.parquet")


@_retry
def _ags(client: Client, url: str, data: dict) -> dict:
    """POST to an ArcGIS endpoint; errors it reports in a 200 body raise."""
    r = client.post(url, data=data, timeout=Timeout(300, connect=30))
    r.raise_for_status()
    body = r.json()
    if "error" in body:
        err = body["error"]
        msg = f"{url}: {err.get('code')} {err.get('message')} (check AGS_TOKEN in .env)"
        raise AgsError(msg, err.get("code"))
    return body


def _ags_token() -> str:
    load_dotenv(root / ".env")
    token = getenv("AGS_TOKEN")
    if not token:
        msg = "AGS_TOKEN missing; add a geoportal.un.org token to .env"
        raise ValueError(msg)
    return token


def _ungeodata(out: Path) -> str:
    """Page each UN Geodata 1M layer into one GeoJSON with features as served."""
    token = _ags_token()
    with _client() as client:
        item = _ags(client, UNGEODATA_ITEM_URL, {"f": "json", "token": token})
        for name, (layer, page) in UNGEODATA_LAYERS.items():
            url = f"{UNGEODATA_URL}/{layer}/query"
            base = {"where": "1=1", "f": "json", "token": token}
            total = _ags(client, url, {**base, "returnCountOnly": "true"})["count"]
            offset = 0
            with (out / f"{name}.geojson").open("w") as f:
                f.write('{"type": "FeatureCollection", "features": [')
                while offset < total:
                    features = _ags(
                        client,
                        url,
                        {
                            **base,
                            "outFields": "*",
                            "outSR": 4326,
                            "f": "geojson",
                            "orderByFields": "objectid",
                            "resultOffset": offset,
                            "resultRecordCount": page,
                        },
                    )["features"]
                    if not features:
                        break
                    for feature in features:
                        f.write(", " if offset else "")
                        json.dump(feature, f)
                        offset += 1
                    logger.info("ungeodata %s: %d of %d", name, offset, total)
                f.write("]}")
            if offset != total:
                msg = f"ungeodata {name}: {offset} features, service reports {total}"
                raise ValueError(msg)
    return datetime.fromtimestamp(item["modified"] / 1000, UTC).date().isoformat()


def _fetch(source: str, fn: Callable[[Path], str]) -> None:
    out = download_dir / source
    rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    (out / ".date").write_text(fn(out))
    logger.info("%s: downloaded", source)


def main() -> None:
    """Download all sources, or exactly ``--only``, in parallel."""
    parser = ArgumentParser()
    parser.add_argument("--only", nargs="+")
    args, _ = parser.parse_known_args()
    jobs = {
        "gaul": partial(_zip, GAUL_URL),
        "lsib": _lsib,
        "osm": _osm,
        "wp": _wp,
        "ref": _ref,
        "fieldmaps": _fieldmaps,
        "wb": _wb,
    }
    # Needs AGS_TOKEN, so only downloaded when named.
    named_only = {"ungeodata": _ungeodata}
    if args.only:
        jobs |= named_only
        if unknown := set(args.only) - set(jobs):
            msg = f"unknown sources: {sorted(unknown)}"
            raise ValueError(msg)
        jobs = {s: fn for s, fn in jobs.items() if s in args.only}
    if "ungeodata" in jobs:
        _ags_token()  # fail before _fetch clears the existing download
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = [pool.submit(_fetch, s, fn) for s, fn in jobs.items()]
    for f in futures:
        f.result()
