import layers from "$lib/layers.json";

// One entry per PMTiles file; pipeline/tiles.py and pipeline/attributes.py read the same layers.json, and the source-layer name is the id.
export interface SourceLayer {
  id: string;
  // Shared by a source's polygon, line and voronoi layers, so a pick carries across modes; also its attributes.json source.
  source: string;
  label: string;
  kind: "polygon" | "line" | "voronoi";
  // Polygon layers only: the feature properties holding the ISO3 code and the feature's name.
  code?: string;
  name?: string;
  // The property naming the entity a geometry difference refers to; Voronoi cells carry it too.
  entity?: string;
}

export const LAYERS = layers as SourceLayer[];
export const LAYER_BY_ID = new Map(LAYERS.map((l) => [l.id, l]));

export const SOURCES = [...new Set(LAYERS.map((l) => l.source))];
export const DEFAULT_PAIR = { a: "gaul", b: "ungeodata" };

// A file's path in the catalog, mirroring pipeline/catalog.py: <source>/<id>/ per layer, differences/ and tables/ otherwise.
export function catalogPath(id: string, ext = "pmtiles"): string {
  const layer = LAYER_BY_ID.get(id);
  const dir = layer ? layer.source : id.startsWith("differences") ? "differences" : "tables";
  return `${dir}/${id}/${id}.${ext}`;
}

export function layerFor(source: string, kind: SourceLayer["kind"]) {
  return LAYERS.find((l) => l.source === source && l.kind === kind)!;
}
