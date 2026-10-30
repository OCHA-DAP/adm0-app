import { DEFAULT_PAIRS, LAYERS, LAYER_BY_ID, type SourceLayer } from "$lib/layers";
import type { Draw, Slot } from "$lib/map/style";

export type Kind = SourceLayer["kind"];
export type View = "overlay" | "swipe" | "lens" | "single";

export interface Hit {
  slot: Slot | null;
  label: string;
  color: string;
  properties: Record<string, unknown>;
}

export const MODES: { id: Kind; label: string }[] = [
  { id: "polygon", label: "Polygons" },
  { id: "line", label: "Lines" },
];
export const VIEWS: { id: View; label: string; hint: string }[] = [
  { id: "overlay", label: "Overlay", hint: "Both sources together. Blink to catch small shifts." },
  { id: "swipe", label: "Swipe", hint: "Drag the divider to scan a border region by region." },
  { id: "lens", label: "Lens", hint: "Check one spot and keep the area around it in view." },
  { id: "single", label: "Single", hint: "One source at a time, to step through them all." },
];
export const SLOT_COLORS: Record<Slot, string> = { a: "#009EDB", b: "#CF3F0B" };

const VIEW_PARAM = "ui";
const BLINK_MS = 600;
const HOLD_MS = 250;
const KEY_SLOT: Record<string, Slot> = { "[": "a", "]": "b" };
const KEY_STEP: Record<string, number> = { "[": -1, "]": 1, "{": -1, "}": 1 };

function step(ids: string[], current: string, by: number) {
  return ids[(ids.indexOf(current) + by + ids.length) % ids.length];
}

export class CompareState {
  mode = $state<Kind>("polygon");
  view = $state<View>(VIEWS.find((v) => v.id === new URLSearchParams(location.search).get(VIEW_PARAM))?.id ?? "overlay");
  pairs = $state(structuredClone(DEFAULT_PAIRS));
  single = $state({ polygon: DEFAULT_PAIRS.polygon.a, line: DEFAULT_PAIRS.line.a });
  keySolo = $state<Slot | null>(null);
  blinking = $state(false);
  blinkSlot = $state<Slot>("a");
  fade = $state(0.5);
  lensRadius = $state(120);
  hits = $state<Hit[]>([]);
  #press: { slot: Slot; at: number; was: Slot | null } | null = null;
  #timer: ReturnType<typeof setInterval> | undefined;

  pair = $derived(this.pairs[this.mode]);
  stacked = $derived(this.view === "swipe" || this.view === "lens");
  solo = $derived(this.keySolo ?? (this.blinking && this.view === "overlay" ? this.blinkSlot : null));
  kindLayers = $derived(LAYERS.filter((l) => l.kind === this.mode));
  singleLayer = $derived(LAYER_BY_ID.get(this.single[this.mode])!);
  viewInfo = $derived(VIEWS.find((v) => v.id === this.view)!);

  mainDraws = $derived.by<Draw[]>(() => {
    if (this.view === "single") return [{ id: this.singleLayer.id, color: this.singleLayer.color, opacity: 1 }];
    if (this.stacked) return [this.#slotDraw("a")];
    if (this.solo) return [this.#slotDraw(this.solo)];
    return [this.#slotDraw("a", Math.min(1, 2 * (1 - this.fade))), this.#slotDraw("b", Math.min(1, 2 * this.fade))];
  });
  overlayDraws = $derived([this.#slotDraw("b")]);

  nowShowing = $derived.by(() => {
    if (this.view === "single") return { color: this.singleLayer.color, label: this.singleLayer.label };
    if (this.solo) return { color: SLOT_COLORS[this.solo], label: `${this.solo.toUpperCase()} only` };
    return null;
  });

  #slotDraw(slot: Slot, opacity = 1): Draw {
    return { id: this.pair[slot], color: SLOT_COLORS[slot], opacity, slot };
  }

  setMode(next: Kind) {
    this.mode = next;
    this.hits = [];
  }

  setView(next: View) {
    this.view = next;
    this.keySolo = null;
    this.hits = [];
    const url = new URL(location.href);
    url.searchParams.set(VIEW_PARAM, next);
    history.replaceState(null, "", url);
  }

  setBlinking(on: boolean) {
    this.blinking = on;
    clearInterval(this.#timer);
    if (on) this.#timer = setInterval(() => (this.blinkSlot = this.blinkSlot === "a" ? "b" : "a"), BLINK_MS);
  }

  swap() {
    this.pairs[this.mode] = { a: this.pair.b, b: this.pair.a };
  }

  keydown(e: KeyboardEvent) {
    if (e.target instanceof HTMLElement && e.target.closest("input, select, textarea")) return;
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
      this.#press = { slot, at: performance.now(), was: this.keySolo };
      this.keySolo = slot;
    }
  }

  // Tapping a key toggles that slot on its own; holding it peeks until release.
  keyup(e: KeyboardEvent) {
    const press = this.#press;
    if (!press || KEY_SLOT[e.key] !== press.slot) return;
    const held = performance.now() - press.at > HOLD_MS;
    this.keySolo = held || press.was === press.slot ? null : press.slot;
    this.#press = null;
  }
}
