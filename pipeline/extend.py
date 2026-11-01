"""Extend each source's polygons into Voronoi cells with topo-tools edge-extend."""

from logging import getLogger
from subprocess import run

from .config import layers, open_db, prepare_dir, tmp_dir, write_parquet

logger = getLogger(__name__)

extend_dir = tmp_dir / "extend"


def extend(layer: dict) -> None:
    """Write ``layer``'s Voronoi cells from its source's polygon layer."""
    polygon = next(
        lyr["id"]
        for lyr in layers()
        if lyr["source"] == layer["source"] and lyr["kind"] == "polygon"
    )
    src = prepare_dir / f"{polygon}.parquet"
    bounded = extend_dir / f"{polygon}_bounded.parquet"
    extend_dir.mkdir(parents=True, exist_ok=True)
    # Vertices a hair past +-180 fall outside edge-extend's clipped Voronoi cells.
    write_parquet(
        open_db(),
        f"""SELECT * REPLACE (CASE
                WHEN ST_XMin(geometry) < -180 OR ST_XMax(geometry) > 180
                  OR ST_YMin(geometry) < -90 OR ST_YMax(geometry) > 90
                THEN ST_Multi(ST_CollectionExtract(ST_Intersection(
                    geometry, ST_MakeEnvelope(-180, -90, 180, 90)), 3))
                ELSE geometry
            END AS geometry)
        FROM read_parquet('{src}')""",
        bounded,
    )
    out = prepare_dir / f"{layer['id']}.parquet"
    logger.info("%s: extending %s", layer["id"], bounded.name)
    run(["topo-tools", "edge-extend", str(bounded), str(out)], check=True)
    bounded.unlink()


def main() -> None:
    """Write one Voronoi layer per source."""
    for layer in layers():
        if layer["kind"] == "voronoi":
            extend(layer)
