import { DEFAULT_PAIRS, LAYERS, LAYER_BY_ID, type SourceLayer } from "$lib/layers";
import type { Draw, Slot } from "$lib/map/style";

export type Kind = SourceLayer["kind"];
export type View = "overlay" | "fade" | "single";
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
export const VIEWS: { id: View; label: string; hint: string }[] = [
  { id: "overlay", label: "Overlay", hint: "Both sources together." },
  { id: "fade", label: "Fade", hint: "A and B fade into each other on a loop, to catch small shifts." },
  { id: "single", label: "Single", hint: "One source at a time, to step through them all." },
];
export const BASEMAPS: { id: Basemap; label: string }[] = [
  { id: "map", label: "Map" },
  { id: "satellite", label: "Satellite" },
];
export const SLOT_COLORS: Record<Slot, string> = { a: "#009EDB", b: "#CF3F0B" };

const VIEW_PARAM = "ui";
const FADE_CYCLE_MS = 3000;
const HOLD_MS = 250;
const KEY_SLOT: Record<string, Slot> = { "[": "a", "]": "b" };
const KEY_STEP: Record<string, number> = { "[": -1, "]": 1, "{": -1, "}": 1 };

function fromUrl() {
  const q = new URLSearchParams(import.meta.env.DEV ? location.search : "");
  const pick = <T extends string>(key: string, ids: T[], fallback: T) => ids.find((id) => id === q.get(key)) ?? fallback;
  const mode = pick("mode", MODES.map((m) => m.id), MODES[0].id);
  const ids = LAYERS.filter((l) => l.kind === mode).map((l) => l.id);
  const pairs = structuredClone(DEFAULT_PAIRS);
  pairs[mode] = { a: pick("a", ids, pairs[mode].a), b: pick("b", ids, pairs[mode].b) };
  const single = { polygon: DEFAULT_PAIRS.polygon.a, line: DEFAULT_PAIRS.line.a };
  single[mode] = pick("src", ids, single[mode]);
  const basemap = pick("basemap", BASEMAPS.map((b) => b.id), "map");
  return { mode, view: pick(VIEW_PARAM, VIEWS.map((v) => v.id), "overlay"), pairs, single, basemap };
}

function step(ids: string[], current: string, by: number) {
  return ids[(ids.indexOf(current) + by + ids.length) % ids.length];
}

export class CompareState {
  #init = fromUrl();
  mode = $state<Kind>(this.#init.mode);
  view = $state<View>(this.#init.view);
  pairs = $state(this.#init.pairs);
  single = $state(this.#init.single);
  basemap = $state<Basemap>(this.#init.basemap);
  solo = $state<Slot | null>(null);
  sweep = $state(0);
  hits = $state<Hit[]>([]);
  #press: { slot: Slot; at: number; was: Slot | null } | null = null;
  #frame = 0;

  pair = $derived(this.pairs[this.mode]);
  kindLayers = $derived(LAYERS.filter((l) => l.kind === this.mode));
  singleLayer = $derived(LAYER_BY_ID.get(this.single[this.mode])!);
  viewInfo = $derived(VIEWS.find((v) => v.id === this.view)!);

  draws = $derived.by<Draw[]>(() => {
    if (this.view === "single") return [{ id: this.singleLayer.id, color: this.singleLayer.color, opacity: 1 }];
    if (this.solo) return [this.#slotDraw(this.solo)];
    if (this.view === "fade") return [this.#slotDraw("a", 1 - this.sweep), this.#slotDraw("b", this.sweep)];
    return [this.#slotDraw("a"), this.#slotDraw("b")];
  });

  nowShowing = $derived.by(() => {
    if (this.view === "single") return { color: this.singleLayer.color, label: this.singleLayer.label };
    if (this.solo) return { color: SLOT_COLORS[this.solo], label: `${this.solo.toUpperCase()} only` };
    return null;
  });

  constructor() {
    this.#animate(this.view === "fade");
  }

  #slotDraw(slot: Slot, opacity = 1): Draw {
    return { id: this.pair[slot], color: SLOT_COLORS[slot], opacity, slot };
  }

  writeParams(params: URLSearchParams) {
    params.set("mode", this.mode);
    params.set(VIEW_PARAM, this.view);
    params.set("basemap", this.basemap);
    for (const key of ["a", "b", "src"]) params.delete(key);
    if (this.view === "single") params.set("src", this.single[this.mode]);
    else for (const slot of ["a", "b"] as const) params.set(slot, this.pair[slot]);
  }

  setMode(next: Kind) {
    this.mode = next;
    this.hits = [];
  }

  setView(next: View) {
    this.view = next;
    this.solo = null;
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
    const picked = VIEWS[Number(e.key) - 1];
    if (picked) {
      if (!e.repeat) this.setView(picked.id);
      return;
    }
    const by = KEY_STEP[e.key];
    const slot = KEY_SLOT[e.key];
    if (by === undefined) return;
    if (this.view === "single") {
      if (slot) this.single[this.mode] = step(this.kindLayers.map((l) => l.id), this.single[this.mode], by);
    } else if (!slot) {
      const ids = this.kindLayers.map((l) => l.id).filter((id) => id !== this.pair.a);
      this.pairs[this.mode].b = step(ids, this.pair.b, by);
    } else if (!e.repeat) {
      this.#press = { slot, at: performance.now(), was: this.solo };
      this.solo = slot;
    }
  }

  // Tapping a key toggles that slot on its own; holding it peeks until release.
  keyup(e: KeyboardEvent) {
    const press = this.#press;
    if (!press || KEY_SLOT[e.key] !== press.slot) return;
    const held = performance.now() - press.at > HOLD_MS;
    this.solo = held || press.was === press.slot ? null : press.slot;
    this.#press = null;
  }
}
