import type { ExpressionSpecification, FilterSpecification, LayerSpecification, Map, StyleSpecification } from "maplibre-gl";
import type { Focus, ItemFocus } from "$lib/compare.svelte";
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
// Islands are OSM land, outside both sources, so they draw in neutral grey instead of a source's colour.
const ISLAND_COLOR = "#424242";
const ISLAND: ExpressionSpecification = ["==", ["get", "type"], "island"];

// "all" draws islands always and land outside Fade; in Fade, "a" and "b" each draw land in one source's color.
const DIFF_SETS = ["all", "a", "b"] as const;
export const DIFF_FILLS = DIFF_SETS.map((k) => `${DIFFERENCES}-${k}-fill`);
// Voronoi area rows only take clicks; the sources' own Voronoi show the rest.
const PATCH: ExpressionSpecification = ["!=", ["get", "type"], "voronoi"];
// Transparent, so a click finds the difference under it, Voronoi area rows included.
export const DIFF_PICK = `${DIFFERENCES}-pick`;
// One point per island difference, on top of source lines; its edge thins out by z12 so it melts into its island.
const DIFF_DOTS = `${DIFFERENCES}_dots`;
const DOTS_LAYER: LayerSpecification = { id: DIFF_DOTS, source: DIFF_DOTS, "source-layer": DIFF_DOTS, layout: { visibility: "none" }, type: "circle", paint: { "circle-color": ISLAND_COLOR, "circle-radius": 4, "circle-stroke-color": "#FFFFFF", "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 8, 1, 12, 0] } };

function differenceLayers(): LayerSpecification[] {
  const common = { source: DIFFERENCES, "source-layer": DIFFERENCES, layout: { visibility: "none" } } as const;
  return [
    ...DIFF_SETS.flatMap((k): LayerSpecification[] => [
      { ...common, id: `${DIFFERENCES}-${k}-fill`, type: "fill", paint: { "fill-color": DIFF_COLOR, "fill-opacity": ["case", ISLAND, 1, DIFF_FILL_OPACITY] } },
      // The white edge keeps a grey island apart from dark satellite water.
      { ...common, id: `${DIFFERENCES}-${k}-line`, type: "line", paint: { "line-color": DIFF_COLOR, "line-width": ["case", ISLAND, 1, 0.5] } },
    ]),
    { ...common, id: DIFF_PICK, type: "fill", paint: { "fill-opacity": 0 } },
  ];
}

// Land border shifts (land patches on side "both") never draw.
const NOT_BORDER: ExpressionSpecification = ["!", ["all", ["==", ["get", "type"], "land"], ["==", ["get", "side"], "both"]]];

// Focused items keep their colours and every other item's patches turn this grey.
const OTHER_ITEM_COLOR = "#9E9E9E";
// Focused land draws only through its entities' tint, so it never looks like a region of its own.
const FOCUSED_LAND_HIDDEN = (items: string[]): ExpressionSpecification => ["!", ["all", ["==", ["get", "type"], "land"], ["in", ["get", "item"], ["literal", items]]]];
// Shows the pair's patches (none when pair is null), limited to kind; Voronoi areas stay pickable either way.
// Tiles name sides by sorted source id, so swapped means slot A holds tile side "b".
export function applyDifferences(map: Map, pair: string | null, fade: boolean, draws: Draw[], swapped: boolean, items: string[] | null, kind: "island" | "land" | null) {
  const split = fade && draws.length === 2;
  const byPair: ExpressionSpecification = ["==", ["get", "pair"], pair];
  const ofKind: ExpressionSpecification[] = kind ? [kind === "island" ? ISLAND : ["!", ISLAND]] : [];
  map.setLayoutProperty(DIFF_PICK, "visibility", pair ? "visible" : "none");
  if (pair) map.setFilter(DIFF_PICK, ["all", byPair, NOT_BORDER, ["any", ["!", PATCH], ...(kind ? ofKind : [true])]]);
  // Every island dot of the pair shows until a difference is picked, then only its own.
  map.setLayoutProperty(DIFF_DOTS, "visibility", pair && kind !== "land" ? "visible" : "none");
  if (pair) map.setFilter(DIFF_DOTS, items ? ["all", byPair, ["in", ["get", "item"], ["literal", items]]] : byPair);
  for (const k of DIFF_SETS) {
    const shown = !!pair && (k === "all" || split);
    const kinds: ExpressionSpecification[] = k === "all" ? (split ? [ISLAND] : []) : [["!", ISLAND]];
    const land = k === "all" ? DIFF_COLOR : draws[(k === "b") !== swapped ? 1 : 0]?.color ?? DIFF_COLOR;
    for (const type of ["fill", "line"] as const) {
      const id = `${DIFFERENCES}-${k}-${type}`;
      map.setLayoutProperty(id, "visibility", shown ? "visible" : "none");
      if (!shown) continue;
      map.setFilter(id, ["all", byPair, NOT_BORDER, PATCH, ...kinds, ...ofKind, ...(items ? [FOCUSED_LAND_HIDDEN(items)] : [])]);
      const color: ExpressionSpecification = ["case", ISLAND, type === "line" ? "#FFFFFF" : ISLAND_COLOR, land];
      map.setPaintProperty(id, `${type}-color`, items ? ["case", ["in", ["get", "item"], ["literal", items]], color, ISLAND, type === "line" ? "#FFFFFF" : OTHER_ITEM_COLOR, OTHER_ITEM_COLOR] : color);
    }
  }
}

// Each source's whole Voronoi cells for a focused difference or code, tinted so islands joined to a mainland read as one.
const ENTITY_FILL_OPACITY = 0.3;
function entityLayersFor(layer: SourceLayer): LayerSpecification[] {
  if (layer.kind !== "voronoi") return [];
  const common = { source: layer.id, "source-layer": layer.id, layout: { visibility: "none" } } as const;
  return [
    { ...common, id: `${layer.id}-entity-fill`, type: "fill", paint: { "fill-color": "transparent", "fill-opacity": ENTITY_FILL_OPACITY } },
    { ...common, id: `${layer.id}-entity`, type: "line", paint: { "line-color": "transparent", "line-width": FOCUS_WIDTH } },
  ];
}

// The cells to tint per source: a difference's entity, or a focused code narrowed to a picked part's feature.
function cellFilter(source: string, item: ItemFocus | null, focus: Focus | null): FilterSpecification | null {
  const polygon = layerFor(source, "polygon");
  if (item) {
    const [code, name] = item.entities[source] ?? [null, null];
    if (code == null && name == null) return null;
    return ["all", ["==", ["get", polygon.code!], code ?? null], ["==", ["get", polygon.entity!], name ?? null]] as FilterSpecification;
  }
  if (!focus) return null;
  const byCode: FilterSpecification = ["==", ["upcase", ["to-string", ["coalesce", ["get", polygon.code!], ""]]], focus.iso3];
  const names = focus.parts.filter((p) => p.layer === polygon.id).map((p) => p.name);
  return names.length ? ["all", byCode, ["in", ["get", polygon.name!], ["literal", names]]] : byCode;
}

// Voronoi tints each drawn source's cells for the focused difference or code.
export function applyVoronoiFocus(map: Map, draws: Draw[], item: ItemFocus | null, focus: Focus | null) {
  for (const layer of LAYERS) {
    if (layer.kind !== "voronoi") continue;
    const draw = draws.find((d) => d.id === layer.id);
    const filter = draw ? cellFilter(layer.source, item, focus) : null;
    const shown = !!filter;
    for (const [id, type] of [[`${layer.id}-entity`, "line"], [`${layer.id}-entity-fill`, "fill"]] as const) {
      map.setLayoutProperty(id, "visibility", shown ? "visible" : "none");
      if (!shown) continue;
      map.setFilter(id, filter);
      map.setPaintProperty(id, `${type}-color`, draw!.color);
    }
  }
}

// Fade calls this every frame with plain numbers only, so nothing is re-evaluated per feature.
// Each source's patches crossfade with its own layers, as in CompareState.opacities.
export function applyDifferenceFade(map: Map, sweep: number, swapped: boolean) {
  for (const k of ["a", "b"] as const) {
    const o = (k === "b") !== swapped ? sweep : 1 - sweep;
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
  const names = focus.parts.filter((p) => p.layer === layer.id).map((p) => p.name);
  return names.length ? names : null;
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
    if (layer.kind === "voronoi") {
      map.setPaintProperty(`${d.id}-entity`, "line-opacity", o);
      map.setPaintProperty(`${d.id}-entity-fill`, "fill-opacity", ENTITY_FILL_OPACITY * o);
    }
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
        [...LAYERS.map((l) => l.id), DIFFERENCES, DIFF_DOTS].map((id) => [id, { type: "vector" as const, url: `pmtiles://${tilesBase}/${id}.pmtiles` }]),
      ),
    },
    layers: [
      ...(positron.layers as LayerSpecification[]),
      { id: "satellite", type: "raster", source: "satellite", layout: { visibility: "none" } },
      ...LAYERS.flatMap(entityLayersFor).filter((l) => l.type === "fill"),
      ...differenceLayers(),
      ...LAYERS.flatMap((l) => layersFor(l, draws)),
      // Every dim sits under every outline, so one source's dim never covers the other's outline.
      ...focus.filter((l) => l.type === "fill"),
      ...focus.filter((l) => l.type === "line"),
      ...LAYERS.flatMap(entityLayersFor).filter((l) => l.type === "line"),
      DOTS_LAYER,
    ],
  };
}
