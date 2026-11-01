import type { ExpressionSpecification, FilterSpecification, LayerSpecification, Map, StyleSpecification } from "maplibre-gl";
import type { Focus } from "$lib/compare.svelte";
import positron from "$lib/utils/basemap/positron.json";
import { LAYERS, LAYER_BY_ID, layerFor, type SourceLayer } from "$lib/layers";
import { SATELLITE } from "$lib/map/satellite";

export type Slot = "a" | "b";

export interface Draw {
  id: string;
  color: string;
  slot?: Slot;
}

const POSITRON_IDS = (positron.layers as LayerSpecification[]).map((l) => l.id);

const FILL_OPACITY = 0.08;
const LINE_WIDTH = 2;
const FOCUS_WIDTH = 4;
const DIM = { map: { color: "#FFFFFF", opacity: 0.7 }, satellite: { color: "#000000", opacity: 0.55 } };

// Line types from the UN Guidelines for the Publication of Maps, in the line_type tile property; dashes are in line widths.
const LINE_TYPES = {
  international: { dash: [1, 0], width: LINE_WIDTH },
  special: { dash: [4, 1.5, 1, 1.5], width: LINE_WIDTH },
  armistice: { dash: [3, 1.5], width: LINE_WIDTH },
  separation: { dash: [1, 1.5], width: LINE_WIDTH },
  autonomous: { dash: [3, 1.5], width: 1.5 },
  sovereign: { dash: [1, 0], width: 1 },
};

function byType(value: (t: (typeof LINE_TYPES)[keyof typeof LINE_TYPES]) => unknown) {
  return ["match", ["get", "line_type"], ...Object.entries(LINE_TYPES).flatMap(([k, t]) => [k, value(t)]), value(LINE_TYPES.international)] as unknown as ExpressionSpecification;
}
const LINE_DASH = byType((t) => ["literal", t.dash]);
const LINE_WIDTHS = byType((t) => t.width);

export const DIFFERENCES = "differences";
export const DIFF_COLOR = "#7B3FA0";
const DIFF_FILL_OPACITY = 0.45;

// "all" draws every patch outside Fade; in Fade, "a" and "b" each draw one tile side's half with a fixed filter and color.
const DIFF_SETS = ["all", "a", "b"] as const;
export const DIFF_FILLS = DIFF_SETS.map((k) => `${DIFFERENCES}-${k}-fill`);

function differenceLayers(): LayerSpecification[] {
  const common = { source: DIFFERENCES, "source-layer": DIFFERENCES, layout: { visibility: "none" } } as const;
  return DIFF_SETS.flatMap((k) => [
    { ...common, id: `${DIFFERENCES}-${k}-fill`, type: "fill", paint: { "fill-color": DIFF_COLOR, "fill-opacity": DIFF_FILL_OPACITY } },
    // Islands get a heavier outline so a small one still shows at low zoom.
    { ...common, id: `${DIFFERENCES}-${k}-line`, type: "line", paint: { "line-color": DIFF_COLOR, "line-width": ["match", ["get", "type"], "island", 2, 0.5] } },
  ]);
}

// A tile side's half: patches only it has, plus border shifts it gives to the alphabetically first country.
function sideFilter(side: "a" | "b"): ExpressionSpecification {
  const other = side === "a" ? "b" : "a";
  const code = (s: string): ExpressionSpecification => ["upcase", ["coalesce", ["get", `${s}_code`], ""]];
  return ["any", ["==", ["get", "side"], side], ["all", ["==", ["get", "side"], "both"], ["<", code(side), code(other)]]];
}

// Shows the pair's patches, or hides them all when pair is null. Tiles name sides by sorted source id,
// so swapped means slot A holds tile side "b".
export function applyDifferences(map: Map, pair: string | null, fade: boolean, draws: Draw[], swapped: boolean) {
  const split = fade && draws.length === 2;
  for (const k of DIFF_SETS) {
    const shown = !!pair && (k === "all") !== split;
    const color = k === "all" ? DIFF_COLOR : draws[(k === "b") !== swapped ? 1 : 0]?.color ?? DIFF_COLOR;
    for (const type of ["fill", "line"] as const) {
      const id = `${DIFFERENCES}-${k}-${type}`;
      map.setLayoutProperty(id, "visibility", shown ? "visible" : "none");
      if (!shown) continue;
      const byPair: ExpressionSpecification = ["==", ["get", "pair"], pair];
      map.setFilter(id, k === "all" ? byPair : ["all", byPair, sideFilter(k)]);
      map.setPaintProperty(id, `${type}-color`, color);
    }
  }
}

// Fade calls this every frame with plain numbers only, so nothing is re-evaluated per feature.
// Each half's patches fade out to the midpoint, then the other half's fade in.
export function applyDifferenceFade(map: Map, sweep: number, swapped: boolean) {
  const pulse = Math.abs(1 - 2 * sweep);
  const slotB = sweep >= 0.5;
  for (const k of ["a", "b"] as const) {
    const o = (k === "b") !== swapped === slotB ? pulse : 0;
    map.setPaintProperty(`${DIFFERENCES}-${k}-fill`, "fill-opacity", DIFF_FILL_OPACITY * o);
    map.setPaintProperty(`${DIFFERENCES}-${k}-line`, "line-opacity", o);
  }
}

// The layer that click queries hit for a source.
export function queryLayerId(id: string) {
  return LAYER_BY_ID.get(id)?.kind === "line" ? `${id}-line` : `${id}-fill`;
}

function layersFor(layer: SourceLayer, draws: Draw[]): LayerSpecification[] {
  const draw = draws.find((d) => d.id === layer.id);
  const color = draw?.color ?? "transparent";
  const common = { source: layer.id, "source-layer": layer.id, layout: { visibility: draw ? "visible" : "none" } } as const;
  const line: LayerSpecification = {
    ...common,
    id: `${layer.id}-line`,
    type: "line",
    paint: {
      "line-color": color,
      "line-width": LINE_WIDTHS,
      "line-dasharray": LINE_DASH,
    },
  };
  if (layer.kind === "line") return [line];
  const fill: LayerSpecification = {
    ...common,
    id: `${layer.id}-fill`,
    type: "fill",
    paint: { "fill-color": color, "fill-opacity": FILL_OPACITY },
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
    { ...common, id: `${layer.id}-focus`, type: "line", paint: { "line-color": "transparent", "line-width": FOCUS_WIDTH } },
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
export const drawFor = (draws: Draw[], layerId: string) => draws.find((d) => LAYER_BY_ID.get(d.id)?.source === LAYER_BY_ID.get(layerId)?.source);

// Pick layers of the drawn sources, A first.
export function pickLayerIds(draws: Draw[]) {
  return draws.flatMap((d) => LAYERS.filter((l) => l.code && l.source === LAYER_BY_ID.get(d.id)?.source).map((l) => `${l.id}-pick`));
}

// A picked part narrows its own layer to that feature; other layers outline the whole code.
function outlined(layer: SourceLayer, focus: Focus): string[] | null {
  return focus.part?.layer === layer.id ? [focus.part.name] : null;
}

export function applyFocus(map: Map, draws: Draw[], focus: Focus | null, fade: boolean, satellite: boolean) {
  for (const layer of LAYERS) {
    if (!layer.code) continue;
    const drawn = drawFor(draws, layer.id);
    map.setLayoutProperty(`${layer.id}-pick`, "visibility", drawn ? "visible" : "none");
    const draw = focus ? drawn : undefined;
    // One dim is enough; stacking a second would darken the surroundings twice.
    // In Fade each source dims at its own opacity, so a code missing from one leaves no undimmed hole.
    const dimmed = !!draw && (fade || draw === draws[0]);
    map.setLayoutProperty(`${layer.id}-focus`, "visibility", draw ? "visible" : "none");
    map.setLayoutProperty(`${layer.id}-dim`, "visibility", dimmed ? "visible" : "none");
    if (!draw || !focus) continue;
    const code: ExpressionSpecification = ["upcase", ["to-string", ["coalesce", ["get", layer.code], ""]]];
    const names = outlined(layer, focus);
    const filter: FilterSpecification = ["==", code, focus.iso3];
    map.setFilter(`${layer.id}-focus`, names ? ["all", filter, ["in", ["get", layer.name!], ["literal", names]]] : filter);
    map.setPaintProperty(`${layer.id}-focus`, "line-color", draw.color);
    if (!dimmed) continue;
    map.setFilter(`${layer.id}-dim`, ["!=", code, focus.iso3]);
    map.setPaintProperty(`${layer.id}-dim`, "fill-color", DIM[satellite ? "satellite" : "map"].color);
  }
}

// Fade calls this every frame, so it sets only the drawn layers' opacities.
export function applyOpacity(map: Map, draws: Draw[], opacities: number[], satellite: boolean) {
  const dim = DIM[satellite ? "satellite" : "map"].opacity;
  draws.forEach((d, i) => {
    const o = opacities[i];
    const layer = LAYER_BY_ID.get(d.id)!;
    const polygon = layerFor(layer.source, "polygon").id;
    map.setPaintProperty(`${d.id}-line`, "line-opacity", o);
    if (layer.kind !== "line") map.setPaintProperty(`${d.id}-fill`, "fill-opacity", FILL_OPACITY * o);
    map.setPaintProperty(`${polygon}-focus`, "line-opacity", o);
    map.setPaintProperty(`${polygon}-dim`, "fill-opacity", dim * o);
  });
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
        [...LAYERS.map((l) => l.id), DIFFERENCES].map((id) => [id, { type: "vector" as const, url: `pmtiles://${tilesBase}/${id}.pmtiles` }]),
      ),
    },
    layers: [
      ...(positron.layers as LayerSpecification[]),
      { id: "satellite", type: "raster", source: "satellite", layout: { visibility: "none" } },
      ...differenceLayers(),
      ...LAYERS.flatMap((l) => layersFor(l, draws)),
      // Every dim sits under every outline, so one source's dim never covers the other's outline.
      ...focus.filter((l) => l.type === "fill"),
      ...focus.filter((l) => l.type === "line"),
    ],
  };
}
