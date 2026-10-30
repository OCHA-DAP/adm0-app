import layers from "$lib/layers.json";

// One entry per PMTiles file; pipeline/tiles.py reads the same layers.json, and the source-layer name is the id.
export interface SourceLayer {
  id: string;
  label: string;
  group: string;
  kind: "polygon" | "line";
  color: string;
}

export const LAYERS = layers as SourceLayer[];
export const LAYER_BY_ID = new Map(LAYERS.map((l) => [l.id, l]));

export const DEFAULT_PAIRS: Record<SourceLayer["kind"], { a: string; b: string }> = {
  polygon: { a: "gaul_l0", b: "ungeodata_polygons" },
  line: { a: "gaul_lines", b: "ungeodata_lines" },
};
