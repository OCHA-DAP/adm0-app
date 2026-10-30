<script lang="ts">
  import { untrack } from "svelte";
  import "maplibre-gl/dist/maplibre-gl.css";
  import * as maplibregl from "maplibre-gl";
  import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
  import { Protocol } from "pmtiles";
  import type { CompareState, Focus, Hit } from "$lib/compare.svelte";
  import { LAYER_BY_ID } from "$lib/layers";
  import { SATELLITE_PROTOCOL, satelliteTile } from "$lib/map/satellite";
  import { applyBasemap, applyDraws, applyFocus, buildStyle, pickLayerIds, queryLayerId } from "$lib/map/style";

  let {
    tilesBase,
    compare,
    active,
    hits,
    inset,
    onpick,
  }: {
    tilesBase: string;
    compare: CompareState;
    active: boolean;
    hits: boolean;
    inset: number;
    onpick: (iso3: string, layer: string, name: string) => void;
  } = $props();
  // Matches the table pane's slide so the globe moves with it.
  const SLIDE_MS = 300;

  // Apparent globe diameter in px at zoom 0 with the default camera, measured.
  const GLOBE_PX_AT_Z0 = 129;
  const GLOBE_FIT = 0.9;
  const SPIN_DEG_PER_S = 6;
  // The compare panel covers the left edge, so a framed code clears it.
  const FOCUS_PAD = { top: 60, right: 40, bottom: 40, left: 320 };
  const FOCUS_MAX_ZOOM = 14;
  const CLICK_PAD = 3;

  maplibregl.setWorkerUrl(workerUrl);

  let container = $state<HTMLDivElement>();
  let map = $state.raw<maplibregl.Map | null>(null);
  let loaded = $state(false);
  let stopSpin = () => {};
  let framed: Focus | null = null;

  function query(m: maplibregl.Map, point: maplibregl.Point): Hit[] {
    const draws = compare.draws;
    const features = m.queryRenderedFeatures(
      [
        [point.x - CLICK_PAD, point.y - CLICK_PAD],
        [point.x + CLICK_PAD, point.y + CLICK_PAD],
      ],
      { layers: draws.map((d) => queryLayerId(d.id)) },
    );
    // Lines mode also reports the polygon under the click, so a click inside a country has attributes to show.
    const lines = draws.filter((d) => LAYER_BY_ID.get(d.id)?.kind === "line");
    const polygons = lines.length ? m.queryRenderedFeatures(point, { layers: pickLayerIds(lines) }) : [];
    return [...features, ...polygons].flatMap((f) => {
      const layer = LAYER_BY_ID.get(f.sourceLayer ?? "");
      const draw = draws.find((d) => LAYER_BY_ID.get(d.id)?.source === layer?.source);
      if (!draw || !layer) return [];
      const label = lines.length ? `${layer.label} ${layer.kind}` : layer.label;
      return [{ slot: draw.slot ?? null, label, color: draw.color, properties: f.properties }];
    });
  }

  $effect(() => {
    if (!container) return;
    const protocol = new Protocol();
    maplibregl.addProtocol("pmtiles", protocol.tile);
    maplibregl.addProtocol(SATELLITE_PROTOCOL, satelliteTile);
    const el = container;
    // MapLibre writes the hash on creation, so a linked position has to be read first.
    const linked = import.meta.env.DEV && location.hash.length > 1;
    const fitZoom = () => Math.log2((GLOBE_FIT * Math.min(el.clientWidth, el.clientHeight)) / GLOBE_PX_AT_Z0);
    const m = new maplibregl.Map({
      container: el,
      style: buildStyle(tilesBase, untrack(() => compare.draws)),
      center: [20, 10],
      zoom: fitZoom(),
      attributionControl: { compact: true },
      hash: import.meta.env.DEV,
    });
    m.once("load", () => (loaded = true));
    m.on("click", (e) => {
      // Rendered order puts later sources first; A's feature should win.
      const ids = pickLayerIds(compare.draws);
      const [hit] = m.queryRenderedFeatures(e.point, { layers: ids }).sort((x, y) => ids.indexOf(x.layer.id) - ids.indexOf(y.layer.id));
      const layer = hit && LAYER_BY_ID.get(hit.sourceLayer);
      if (layer?.code) onpick(String(hit.properties[layer.code] ?? "").toUpperCase(), layer.id, String(hit.properties[layer.name!] ?? ""));
      if (!hits) return;
      const all = query(m, e.point);
      const seen = new Set<string>();
      compare.hits = all.filter((h) => {
        const key = `${h.slot}:${h.label}:${JSON.stringify(h.properties)}`;
        return !seen.has(key) && !!seen.add(key);
      });
    });
    let frame = 0;
    let last = performance.now();
    const spin = (now: number) => {
      const c = m.getCenter();
      // Clamp so a backgrounded tab doesn't jump ahead on return.
      m.setCenter([c.lng - (Math.min(now - last, 100) / 1000) * SPIN_DEG_PER_S, c.lat]);
      last = now;
      frame = requestAnimationFrame(spin);
    };
    // Dev holds still so tests and screenshots are repeatable.
    if (!import.meta.env.DEV) frame = requestAnimationFrame(spin);
    const refit = new ResizeObserver(() => el.clientWidth && m.setZoom(fitZoom()));
    refit.observe(el);
    const stop = new AbortController();
    stop.signal.addEventListener("abort", () => {
      cancelAnimationFrame(frame);
      refit.disconnect();
    });
    for (const type of ["pointerdown", "wheel", "keydown"]) {
      el.addEventListener(type, () => stop.abort(), { capture: true, signal: stop.signal });
    }
    if (linked) stop.abort();
    stopSpin = () => stop.abort();
    if (import.meta.env.DEV) Object.assign(window, { map: m });
    map = m;
    return () => {
      stop.abort();
      m.remove();
      map = null;
      loaded = false;
      maplibregl.removeProtocol("pmtiles");
      maplibregl.removeProtocol(SATELLITE_PROTOCOL);
    };
  });

  $effect(() => {
    if (map && loaded) applyDraws(map, compare.draws);
  });

  $effect(() => {
    if (map && loaded) applyFocus(map, compare.draws, compare.focus, compare.basemap === "satellite");
  });

  // Each pick frames once, after the layout settles so a pane that just opened has its final size.
  $effect(() => {
    const focus = compare.focus;
    if (!map || !loaded || !active || !focus?.bbox || focus === framed) return;
    framed = focus;
    if (!focus.fly) return;
    stopSpin();
    const [m, bbox] = [map, focus.bbox as [number, number, number, number]];
    requestAnimationFrame(() => {
      m.resize();
      m.fitBounds(bbox, { padding: FOCUS_PAD, maxZoom: FOCUS_MAX_ZOOM });
    });
  });

  $effect(() => {
    if (map && loaded) applyBasemap(map, compare.basemap === "satellite");
  });

  // A pane over the map's right edge pads the camera instead of resizing the canvas.
  $effect(() => {
    if (!map || !loaded) return;
    const still = !active || matchMedia("(prefers-reduced-motion: reduce)").matches;
    map.easeTo({ padding: { top: 0, bottom: 0, left: 0, right: inset }, duration: untrack(() => (still ? 0 : SLIDE_MS)) });
  });

  $effect(() => {
    if (active) requestAnimationFrame(() => map?.resize());
  });
</script>

<svelte:window onkeydown={(e) => active && compare.keydown(e)} />

<div class="map" bind:this={container} style:--inset="{inset}px"></div>
<div class="pills" style:--inset="{inset}px">
  {#if compare.focus}
    <button class="pill focus" aria-label="Clear highlight" onclick={() => (compare.focus = null)}>{compare.focus.iso3} <span aria-hidden="true">×</span></button>
  {/if}
</div>

<style>
  .map {
    flex: 1;
  }
  .map :global(.maplibregl-ctrl-bottom-right) {
    right: var(--inset);
    transition: right 300ms cubic-bezier(0.2, 0, 0, 1);
  }
  .pills {
    position: absolute;
    top: 0.75rem;
    left: calc((100% - var(--inset)) / 2);
    transform: translateX(-50%);
    transition: left 300ms cubic-bezier(0.2, 0, 0, 1);
    display: flex;
    gap: 0.5rem;
    pointer-events: none;
    z-index: 3;
  }
  .pill {
    padding: 0.3rem 0.75rem;
    background: var(--cd-white);
    border-radius: 999px;
    box-shadow: var(--panel-shadow);
    font-size: 0.875rem;
    font-weight: 600;
    white-space: nowrap;
  }
  .focus {
    border: 0;
    color: inherit;
    font-family: inherit;
    pointer-events: auto;
    cursor: pointer;
  }
  .focus span {
    margin-left: 0.25rem;
    color: var(--brand-grey--text);
  }
</style>
