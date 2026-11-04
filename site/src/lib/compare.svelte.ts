import { DEFAULT_PAIR, LAYERS, SOURCES, layerFor, type SourceLayer } from "$lib/layers";
import { unionBox, type ItemRow, type Part } from "$lib/attributes";
import type { Draw, Slot } from "$lib/map/style";

// Voronoi also draws the pair's differing OSM land and islands over the sources' cells.
export type Kind = SourceLayer["kind"];
export type View = "fade" | Slot;
export type Basemap = "map" | "satellite";

export interface Hit {
  slot: Slot | null;
  label: string;
  color: string;
  properties: Record<string, unknown>;
}

// A code picked in the table or on the map, optionally narrowed to one feature; fly frames it.
export interface Focus {
  iso3: string;
  bbox: number[] | null;
  parts: Part[];
  fly: boolean;
}

// A table row's merged geometry differences, by id; the map outlines their patches and each source's
// cells for their territories, keyed by source as [code, name] lists, and frames their bbox.
export interface ItemFocus {
  ids: string[];
  label: string;
  bbox: number[] | null;
  entities: Record<string, [unknown, unknown][]>;
  fly: boolean;
}

export const MODES: { id: Kind; label: string }[] = [
  { id: "line", label: "Lines" },
  { id: "polygon", label: "Polygons" },
  { id: "voronoi", label: "Voronoi" },
];
export const VIEWS: { id: View; label: string }[] = [
  { id: "fade", label: "Fade" },
  { id: "a", label: "A" },
  { id: "b", label: "B" },
];
export const BASEMAPS: { id: Basemap; label: string }[] = [
  { id: "map", label: "Map" },
  { id: "satellite", label: "Satellite" },
];
export const SLOT_COLORS: Record<Slot, string> = { a: "#009EDB", b: "#CF3F0B" };

const VIEW_PARAM = "ui";
const FADE_CYCLE_MS = 3000;
const KEY_STEP: Record<string, number> = { "[": -1, "]": 1 };

function fromUrl() {
  const q = new URLSearchParams(import.meta.env.DEV ? location.search : "");
  const pick = <T extends string>(key: string, ids: T[], fallback: T) => ids.find((id) => id === q.get(key)) ?? fallback;
  const mode = pick("mode", MODES.map((m) => m.id), MODES[0].id);
  const pair = { a: pick("a", SOURCES, DEFAULT_PAIR.a), b: pick("b", SOURCES, DEFAULT_PAIR.b) };
  const basemap = pick("basemap", BASEMAPS.map((b) => b.id), "map");
  const code = q.get("focus");
  const focus: Focus | null = code ? { iso3: code.toUpperCase(), bbox: null, parts: [], fly: false } : null;
  return { mode, view: pick(VIEW_PARAM, VIEWS.map((v) => v.id), "fade"), pair, basemap, focus };
}

export class CompareState {
  #init = fromUrl();
  mode = $state<Kind>(this.#init.mode);
  view = $state<View>(this.#init.view);
  pair = $state(this.#init.pair);
  basemap = $state<Basemap>(this.#init.basemap);
  sweep = $state(0);
  hits = $state<Hit[]>([]);
  focus = $state.raw<Focus | null>(this.#init.focus);
  item = $state.raw<ItemFocus | null>(null);
  #frame = 0;

  kindLayers = $derived(LAYERS.filter((l) => l.kind === this.mode));
  // Difference tiles key each source pair as its sorted ids.
  diffPair = $derived([this.pair.a, this.pair.b].sort().join("|"));

  draws = $derived.by<Draw[]>(() => {
    if (this.view === "a" || this.view === "b") return [this.#slotDraw(this.view)];
    return [this.#slotDraw("a"), this.#slotDraw("b")];
  });

  // Kept apart from draws so Fade's per-frame change touches only opacity.
  opacities = $derived(this.view === "fade" ? [1 - this.sweep, this.sweep] : this.draws.map(() => 1));

  #slotDraw(slot: Slot): Draw {
    return { id: layerFor(this.pair[slot], this.mode).id, color: SLOT_COLORS[slot], slot };
  }

  writeParams(params: URLSearchParams) {
    params.set("mode", this.mode);
    params.set(VIEW_PARAM, this.view);
    params.set("basemap", this.basemap);
    for (const slot of ["a", "b"] as const) params.set(slot, this.pair[slot]);
    if (this.focus) params.set("focus", this.focus.iso3);
    else params.delete("focus");
  }

  setMode(next: Kind) {
    this.mode = next;
    this.hits = [];
  }

  setView(next: View) {
    this.view = next;
    this.hits = [];
  }

  focusOn(iso3: string, bbox: number[] | null, parts: Part[], fly: boolean) {
    this.focus = { iso3, bbox: parts.length ? unionBox(parts.map((p) => p.bbox)) : bbox, parts, fly };
    this.item = null;
  }

  // Shows the item in Voronoi, moving to a pair it differs in when the current pair has no patches for it.
  focusItem(row: ItemRow, label: string, fly = true) {
    this.setMode("voronoi");
    const pairs = row.pairs ?? [];
    if (pairs.length && !pairs.includes(this.diffPair)) {
      const [a, b] = pairs[0].split("|");
      this.pair = { a, b };
    }
    this.focus = null;
    const entities = Object.fromEntries(SOURCES.map((s) => [s, row.entities?.[s] ?? [[row[`code_${s}`], row[`name_${s}`]] as [unknown, unknown]]]));
    this.item = { ids: row.items ?? [row.item], label, bbox: row.bbox, entities, fly };
  }

  animate(on: boolean) {
    cancelAnimationFrame(this.#frame);
    if (!on) return;
    const start = performance.now();
    const tick = (now: number) => {
      this.sweep = (1 - Math.cos((2 * Math.PI * (now - start)) / FADE_CYCLE_MS)) / 2;
      this.#frame = requestAnimationFrame(tick);
    };
    this.#frame = requestAnimationFrame(tick);
  }

  keydown(e: KeyboardEvent) {
    if (e.target instanceof HTMLElement && e.target.closest("input:not([type=radio]), select, textarea")) return;
    if (e.key === "Escape") this.focus = this.item = null;
    const by = KEY_STEP[e.key];
    if (by === undefined) return;
    const at = VIEWS.findIndex((v) => v.id === this.view) + by;
    if (VIEWS[at]) this.setView(VIEWS[at].id);
  }
}
