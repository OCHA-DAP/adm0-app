import layers from "$lib/layers.json";

// One entry per PMTiles file; pipeline/tiles.py reads the same layers.json, and the source-layer name is the id.
export interface SourceLayer {
  id: string;
  // Shared by a source's polygon and line layers, so a pick carries across modes.
  source: string;
  label: string;
  group: string;
  kind: "polygon" | "line";
  color: string;
}

export const LAYERS = layers as SourceLayer[];
export const LAYER_BY_ID = new Map(LAYERS.map((l) => [l.id, l]));

export const SOURCES = [...new Set(LAYERS.map((l) => l.source))];
export const DEFAULT_PAIR = { a: "gaul", b: "ungeodata" };

export function layerFor(source: string, kind: SourceLayer["kind"]) {
  return LAYERS.find((l) => l.source === source && l.kind === kind)!;
}
