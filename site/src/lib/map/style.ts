import type { DataDrivenPropertyValueSpecification, ExpressionSpecification, FilterSpecification, LayerSpecification, Map, StyleSpecification } from "maplibre-gl";
import type { Focus } from "$lib/compare.svelte";
import positron from "$lib/utils/basemap/positron.json";
import { LAYERS, LAYER_BY_ID, type SourceLayer } from "$lib/layers";
import { SATELLITE } from "$lib/map/satellite";

export type Slot = "a" | "b";

export interface Draw {
  id: string;
  color: string;
  opacity: number;
  slot?: Slot;
}

const POSITRON_IDS = (positron.layers as LayerSpecification[]).map((l) => l.id);

const FILL_OPACITY = 0.08;
const LINE_WIDTH = 2;
const FOCUS_WIDTH = 4;
const DIM = { map: { color: "#FFFFFF", opacity: 0.7 }, satellite: { color: "#000000", opacity: 0.55 } };

// Line types from the UN Guidelines for the Publication of Maps; dashes are in line widths.
const LINE_TYPES = {
  international: { dash: [1, 0], width: LINE_WIDTH },
  special: { dash: [4, 1.5, 1, 1.5], width: LINE_WIDTH },
  armistice: { dash: [3, 1.5], width: LINE_WIDTH },
  separation: { dash: [1, 1.5], width: LINE_WIDTH },
  autonomous: { dash: [3, 1.5], width: 1.5 },
  sovereign: { dash: [1, 0], width: 1 },
};
type LineType = keyof typeof LINE_TYPES;

const LSIB_TYPE: ExpressionSpecification = [
  "case",
  ["in", "Line of Control", ["coalesce", ["get", "label"], ["get", "LABEL"], ""]],
  "separation",
  [
    "match",
    ["coalesce", ["get", "status"], ["get", "STATUS"]],
    "Special Line",
    "special",
    "Other Line of International Separation",
    "armistice",
    "international",
  ],
];
const LINE_TYPE: Record<string, ExpressionSpecification> = {
  ungeodata_lines: ["match", ["get", "bdytyp"], 2, "special", 3, "armistice", 4, "separation", 8, "autonomous", 9, "sovereign", "international"],
  lsib_lines: LSIB_TYPE,
  fieldmaps_lines: LSIB_TYPE,
};

function byType(id: string, prop: "dash" | "width") {
  const value = (t: (typeof LINE_TYPES)[LineType]) => (prop === "dash" ? ["literal", t.dash] : t.width);
  const type = LINE_TYPE[id];
  if (!type) return value(LINE_TYPES.international);
  return ["match", type, ...Object.entries(LINE_TYPES).flatMap(([k, t]) => [k, value(t)]), value(LINE_TYPES.international)];
}

// The layer that click queries hit for a source.
export function queryLayerId(id: string) {
  return LAYER_BY_ID.get(id)?.kind === "polygon" ? `${id}-fill` : `${id}-line`;
}

function layersFor(layer: SourceLayer, draws: Draw[]): LayerSpecification[] {
  const draw = draws.find((d) => d.id === layer.id);
  const opacity = draw?.opacity ?? 0;
  const color = draw?.color ?? layer.color;
  const common = { source: layer.id, "source-layer": layer.id, layout: { visibility: draw ? "visible" : "none" } } as const;
  const line: LayerSpecification = {
    ...common,
    id: `${layer.id}-line`,
    type: "line",
    paint: {
      "line-color": color,
      "line-width": byType(layer.id, "width") as DataDrivenPropertyValueSpecification<number>,
      "line-opacity": opacity,
      "line-dasharray": byType(layer.id, "dash") as DataDrivenPropertyValueSpecification<number[]>,
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

// Drawn above every source so a focused code stands out; line tiles carry no ISO3, so these use polygons.
function focusLayersFor(layer: SourceLayer): LayerSpecification[] {
  if (!layer.code) return [];
  const common = { source: layer.id, "source-layer": layer.id, layout: { visibility: "none" } } as const;
  return [
    { ...common, id: `${layer.id}-dim`, type: "fill", paint: { "fill-color": DIM.map.color, "fill-opacity": DIM.map.opacity } },
    // Transparent, so a click finds the code under it in Lines mode too.
    { ...common, id: `${layer.id}-pick`, type: "fill", paint: { "fill-opacity": 0 } },
    { ...common, id: `${layer.id}-focus`, type: "line", paint: { "line-color": layer.color, "line-width": FOCUS_WIDTH } },
  ];
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
  }
}

// A source's line layer draws in Lines mode, so draws match polygon layers by source.
const drawFor = (draws: Draw[], layerId: string) => draws.find((d) => LAYER_BY_ID.get(d.id)?.source === LAYER_BY_ID.get(layerId)?.source);

// Pick layers of the drawn sources, A first.
export function pickLayerIds(draws: Draw[]) {
  return draws.flatMap((d) => LAYERS.filter((l) => l.code && l.source === LAYER_BY_ID.get(d.id)?.source).map((l) => `${l.id}-pick`));
}

// A picked part narrows its own layer to that feature; other layers outline the whole code.
function outlined(layer: SourceLayer, focus: Focus): string[] | null {
  return focus.part?.layer === layer.id ? [focus.part.name] : null;
}

export function applyFocus(map: Map, draws: Draw[], focus: Focus | null, satellite: boolean) {
  const dim = DIM[satellite ? "satellite" : "map"];
  for (const layer of LAYERS) {
    if (!layer.code) continue;
    const drawn = drawFor(draws, layer.id);
    map.setLayoutProperty(`${layer.id}-pick`, "visibility", drawn ? "visible" : "none");
    const draw = focus ? drawn : undefined;
    // One dim is enough; stacking a second would darken the surroundings twice.
    // In Fade each source dims at its own opacity, so a code missing from one leaves no undimmed hole.
    const fading = draws.some((d) => d.opacity < 1);
    const dimmed = !!draw && (fading || draw === draws[0]);
    map.setLayoutProperty(`${layer.id}-focus`, "visibility", draw ? "visible" : "none");
    map.setLayoutProperty(`${layer.id}-dim`, "visibility", dimmed ? "visible" : "none");
    if (!draw || !focus) continue;
    const code: ExpressionSpecification = ["upcase", ["to-string", ["coalesce", ["get", layer.code], ""]]];
    const names = outlined(layer, focus);
    const filter: FilterSpecification = ["==", code, focus.iso3];
    map.setFilter(`${layer.id}-focus`, names ? ["all", filter, ["in", ["get", layer.name!], ["literal", names]]] : filter);
    map.setPaintProperty(`${layer.id}-focus`, "line-color", draw.color);
    map.setPaintProperty(`${layer.id}-focus`, "line-opacity", draw.opacity);
    if (!dimmed) continue;
    map.setFilter(`${layer.id}-dim`, ["!=", code, focus.iso3]);
    map.setPaintProperty(`${layer.id}-dim`, "fill-color", dim.color);
    map.setPaintProperty(`${layer.id}-dim`, "fill-opacity", dim.opacity * (fading ? draw.opacity : 1));
  }
}

export function applyBasemap(map: Map, satellite: boolean) {
  for (const id of POSITRON_IDS) map.setLayoutProperty(id, "visibility", satellite ? "none" : "visible");
  map.setLayoutProperty("satellite", "visibility", satellite ? "visible" : "none");
}

export function buildStyle(tilesBase: string, draws: Draw[]): StyleSpecification {
  const focus = LAYERS.flatMap(focusLayersFor);
  return {
    version: 8,
    projection: { type: "globe" },
    // Fade drives opacity every frame, so built-in easing would only make it lag.
    transition: { duration: 0, delay: 0 },
    sprite: positron.sprite,
    glyphs: positron.glyphs,
    sources: {
      ...(positron.sources as StyleSpecification["sources"]),
      satellite: SATELLITE,
      ...Object.fromEntries(
        LAYERS.map((l) => [l.id, { type: "vector" as const, url: `pmtiles://${tilesBase}/${l.id}.pmtiles` }]),
      ),
    },
    layers: [
      ...(positron.layers as LayerSpecification[]),
      { id: "satellite", type: "raster", source: "satellite", layout: { visibility: "none" } },
      ...LAYERS.flatMap((l) => layersFor(l, draws)),
      // Every dim sits under every outline, so one source's dim never covers the other's outline.
      ...focus.filter((l) => l.type === "fill"),
      ...focus.filter((l) => l.type === "line"),
    ],
  };
}
