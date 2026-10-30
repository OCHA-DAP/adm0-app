import type { AddProtocolAction, RasterSourceSpecification } from "maplibre-gl";

export const SATELLITE_PROTOCOL = "esri";
const TILE = 256;
const MAX_STEPS = 8;

export const SATELLITE: RasterSourceSpecification = {
  type: "raster",
  tiles: [`${SATELLITE_PROTOCOL}://{z}/{x}/{y}`],
  tileSize: TILE,
  maxzoom: 19,
  attribution: "Powered by Esri | Esri, Vantor, Earthstar Geographics, and the GIS User Community",
};

// Missing tiles 404 without CORS headers, so any failed fetch counts as no imagery.
async function fetchTile(z: number, x: number, y: number, signal: AbortSignal) {
  const url = `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${y}/${x}?blankTile=false`;
  try {
    const res = await fetch(url, { signal });
    return res.ok ? await res.blob() : null;
  } catch (e) {
    if (signal.aborted) throw e;
    return null;
  }
}

// Imagery depth varies by place, so a missing tile is cropped and enlarged from the nearest ancestor.
export const satelliteTile: AddProtocolAction = async (params, abort) => {
  const [z, x, y] = params.url.slice(`${SATELLITE_PROTOCOL}://`.length).split("/").map(Number);
  for (let d = 0; d <= Math.min(z, MAX_STEPS); d++) {
    const blob = await fetchTile(z - d, x >> d, y >> d, abort.signal);
    if (!blob) continue;
    if (d === 0) return { data: await blob.arrayBuffer() };
    const size = TILE >> d;
    const mask = (1 << d) - 1;
    const data = await createImageBitmap(blob, (x & mask) * size, (y & mask) * size, size, size, {
      resizeWidth: TILE,
      resizeHeight: TILE,
      resizeQuality: "high",
    });
    return { data };
  }
  throw new Error(`No satellite imagery for ${z}/${x}/${y}`);
};
