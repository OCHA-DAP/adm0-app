import { DEFAULT_PAIR, LAYERS, SOURCES, layerFor, type SourceLayer } from "$lib/layers";
import type { Draw, Slot } from "$lib/map/style";

export type Kind = SourceLayer["kind"];
export type View = "overlay" | "fade" | Slot;
export type Basemap = "map" | "satellite";

export interface Hit {
  slot: Slot | null;
  label: string;
  color: string;
  properties: Record<string, unknown>;
}

export const MODES: { id: Kind; label: string }[] = [
  { id: "line", label: "Lines" },
  { id: "polygon", label: "Polygons" },
];
export const VIEWS: { id: View; label: string }[] = [
  { id: "overlay", label: "Overlay" },
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
  return { mode, view: pick(VIEW_PARAM, VIEWS.map((v) => v.id), "overlay"), pair, basemap };
}

export class CompareState {
  #init = fromUrl();
  mode = $state<Kind>(this.#init.mode);
  view = $state<View>(this.#init.view);
  pair = $state(this.#init.pair);
  basemap = $state<Basemap>(this.#init.basemap);
  sweep = $state(0);
  hits = $state<Hit[]>([]);
  #frame = 0;

  kindLayers = $derived(LAYERS.filter((l) => l.kind === this.mode));

  draws = $derived.by<Draw[]>(() => {
    if (this.view === "a" || this.view === "b") return [this.#slotDraw(this.view)];
    if (this.view === "fade") return [this.#slotDraw("a", 1 - this.sweep), this.#slotDraw("b", this.sweep)];
    return [this.#slotDraw("a"), this.#slotDraw("b")];
  });

  nowShowing = $derived(this.view === "a" || this.view === "b" ? { color: SLOT_COLORS[this.view], label: `${this.view.toUpperCase()} only` } : null);

  constructor() {
    this.#animate(this.view === "fade");
  }

  #slotDraw(slot: Slot, opacity = 1): Draw {
    return { id: layerFor(this.pair[slot], this.mode).id, color: SLOT_COLORS[slot], opacity, slot };
  }

  writeParams(params: URLSearchParams) {
    params.set("mode", this.mode);
    params.set(VIEW_PARAM, this.view);
    params.set("basemap", this.basemap);
    for (const slot of ["a", "b"] as const) params.set(slot, this.pair[slot]);
  }

  setMode(next: Kind) {
    this.mode = next;
    this.hits = [];
  }

  setView(next: View) {
    this.view = next;
    this.#animate(next === "fade");
    this.hits = [];
  }

  #animate(on: boolean) {
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
    const by = KEY_STEP[e.key];
    if (by === undefined) return;
    const at = VIEWS.findIndex((v) => v.id === this.view) + by;
    if (VIEWS[at]) this.setView(VIEWS[at].id);
  }
}
