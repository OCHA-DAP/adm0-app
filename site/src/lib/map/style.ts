import type { LayerSpecification, Map, StyleSpecification } from "maplibre-gl";
import positron from "$lib/utils/basemap/positron.json";
import { LAYERS, LAYER_BY_ID, type SourceLayer } from "$lib/layers";

export type Slot = "a" | "b";

export interface Draw {
  id: string;
  color: string;
  dashed: boolean;
  opacity: number;
  slot?: Slot;
}

const DASH = [3, 2];
const FILL_OPACITY = 0.08;

// The layer that click queries hit for a source.
export function queryLayerId(id: string) {
  return LAYER_BY_ID.get(id)?.kind === "polygon" ? `${id}-fill` : `${id}-line`;
}

function layersFor(layer: SourceLayer, draws: Draw[]): LayerSpecification[] {
  const draw = draws.find((d) => d.id === layer.id);
  const opacity = draw?.opacity ?? 0;
  const color = draw?.color ?? layer.color;
  const common = { source: layer.id, "source-layer": layer.id, layout: { visibility: opacity > 0 ? "visible" : "none" } } as const;
  const line: LayerSpecification = {
    ...common,
    id: `${layer.id}-line`,
    type: "line",
    paint: {
      "line-color": color,
      "line-width": 2,
      "line-opacity": opacity,
      ...(draw?.dashed ? { "line-dasharray": DASH } : {}),
    },
  };
  if (layer.kind === "line") return [line];
  const fill: LayerSpecification = {
    ...common,
    id: `${layer.id}-fill`,
    type: "fill",
    paint: { "fill-color": color, "fill-opacity": FILL_OPACITY * opacity },
  };
  return [fill, line];
}

type Setter = (id: string, name: string, value: unknown) => void;

export function applyDraws(map: Map, draws: Draw[]) {
  // Keys come straight from layersFor's own specs, so they are valid property names.
  const setLayout = map.setLayoutProperty.bind(map) as Setter;
  const setPaint = map.setPaintProperty.bind(map) as Setter;
  for (const spec of LAYERS.flatMap((l) => layersFor(l, draws))) {
    const { id, layout, paint } = spec as LayerSpecification & { layout: object; paint: object };
    for (const [k, v] of Object.entries(layout)) setLayout(id, k, v);
    for (const [k, v] of Object.entries(paint)) setPaint(id, k, v);
    if (spec.type === "line" && !("line-dasharray" in paint)) setPaint(id, "line-dasharray", undefined);
  }
}

export function buildStyle(tilesBase: string, draws: Draw[]): StyleSpecification {
  return {
    version: 8,
    projection: { type: "globe" },
    sprite: positron.sprite,
    glyphs: positron.glyphs,
    sources: {
      ...(positron.sources as StyleSpecification["sources"]),
      ...Object.fromEntries(
        LAYERS.map((l) => [l.id, { type: "vector" as const, url: `pmtiles://${tilesBase}/${l.id}.pmtiles` }]),
      ),
    },
    layers: [...(positron.layers as LayerSpecification[]), ...LAYERS.flatMap((l) => layersFor(l, draws))],
  };
}
