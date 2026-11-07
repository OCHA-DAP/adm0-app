<script lang="ts">
  import { untrack } from "svelte";
  import "maplibre-gl/dist/maplibre-gl.css";
  import * as maplibregl from "maplibre-gl";
  import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
  import { Protocol } from "pmtiles";
  import type { CompareState, Focus, Hit, ItemFocus } from "$lib/compare.svelte";
  import { LAYER_BY_ID } from "$lib/layers";
  import { SATELLITE_PROTOCOL, satelliteTile } from "$lib/map/satellite";
  import { DIFFERENCES, DIFF_COLOR, DIFF_FILLS, DIFF_PICK, applyBasemap, applyDifferenceFade, applyDifferences, applyDraws, applyFocus, applyOpacity, applyVoronoiFocus, buildStyle, drawFor, globeFitZoom, pickLayerIds, queryLayerId } from "$lib/map/style";

  let {
    tilesBase,
    compare,
    active,
    hits,
    inset,
    listItems,
    onpick,
    onitempick,
  }: {
    tilesBase: string;
    compare: CompareState;
    active: boolean;
    hits: boolean;
    inset: number;
    listItems: string[] | null;
    onpick: (iso3: string, layer: string, name: string) => void;
    onitempick: (item: string | null) => void;
  } = $props();
  // Matches the table pane's slide so the globe moves with it.
  const SLIDE_MS = 300;

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
  let framed: Focus | ItemFocus | null = null;

  // picked is the click's pick-layer features, reused for the polygons under a line click.
  function query(m: maplibregl.Map, point: maplibregl.Point, picked: maplibregl.MapGeoJSONFeature[]): Hit[] {
    const draws = compare.draws;
    const features = m.queryRenderedFeatures(
      [
        [point.x - CLICK_PAD, point.y - CLICK_PAD],
        [point.x + CLICK_PAD, point.y + CLICK_PAD],
      ],
      { layers: [...draws.map((d) => queryLayerId(d.id)), ...(compare.mode === "voronoi" ? DIFF_FILLS : [])] },
    );
    // Lines mode also reports the polygon under the click, so a click inside a country has attributes to show.
    const lines = compare.mode === "line";
    return [...features, ...(lines ? picked : [])].flatMap((f) => {
      if (f.sourceLayer === DIFFERENCES) return [{ slot: null, label: "Difference", color: DIFF_COLOR, properties: { type: f.properties.type, km2: Number(f.properties.km2).toFixed(2) } }];
      const layer = LAYER_BY_ID.get(f.sourceLayer ?? "");
      const draw = drawFor(draws, f.sourceLayer ?? "");
      if (!draw || !layer) return [];
      const label = lines ? `${layer.label} ${layer.kind}` : layer.label;
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
    const m = new maplibregl.Map({
      container: el,
      style: buildStyle(tilesBase, untrack(() => compare.draws)),
      center: [20, 10],
      zoom: globeFitZoom(el),
      attributionControl: { compact: true },
      hash: import.meta.env.DEV,
    });
    m.once("load", () => (loaded = true));
    m.on("click", (e) => {
      // On a Geometry list, a Voronoi click picks the difference there, a patch before its area.
      const picksItem = !hits && compare.mode === "voronoi" && !!listItems;
      if (picksItem) {
        const box: [maplibregl.PointLike, maplibregl.PointLike] = [[e.point.x - CLICK_PAD, e.point.y - CLICK_PAD], [e.point.x + CLICK_PAD, e.point.y + CLICK_PAD]];
        const found = m.queryRenderedFeatures(box, { layers: [DIFF_PICK] }).sort((x, y) => Number(x.properties.type === "voronoi") - Number(y.properties.type === "voronoi"));
        onitempick(found[0]?.properties.item ?? null);
      }
      // Rendered order puts later sources first; A's feature should win.
      const ids = pickLayerIds(compare.draws);
      const picked = m.queryRenderedFeatures(e.point, { layers: ids }).sort((x, y) => ids.indexOf(x.layer.id) - ids.indexOf(y.layer.id));
      const hit = picked[0];
      const layer = hit && LAYER_BY_ID.get(hit.sourceLayer ?? "");
      // Voronoi clicks on the Map tab only report what each source assigns there, so the patches stay unobscured.
      if (layer?.code && !picksItem && (!hits || compare.mode !== "voronoi")) onpick(String(hit.properties[layer.code] ?? "").toUpperCase(), layer.id, String(hit.properties[layer.name!] ?? ""));
      const seen = new Set<string>();
      compare.hits = query(m, e.point, picked).filter((h) => {
        const key = `${h.slot}:${h.label}:${JSON.stringify(h.properties)}`;
        return !seen.has(key) && !!seen.add(key);
      });
    });
    let frame = 0;
    let last = performance.now();
    const spin = (now: number) => {
      const c = m.getCenter();
      // Clamp so a backgrounded tab doesn't jump ahead on return; a covered map holds still.
      if (active) m.setCenter([c.lng - (Math.min(now - last, 100) / 1000) * SPIN_DEG_PER_S, c.lat]);
      last = now;
      frame = requestAnimationFrame(spin);
    };
    // Dev holds still so tests and screenshots are repeatable.
    if (!import.meta.env.DEV) frame = requestAnimationFrame(spin);
    const refit = new ResizeObserver(() => el.clientWidth && m.setZoom(globeFitZoom(el)));
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
    const pair = compare.mode === "voronoi" ? compare.diffPair : null;
    if (map && loaded) applyDifferences(map, pair, compare.view === "fade", compare.draws, compare.pair.a > compare.pair.b, compare.item?.ids ?? null, listItems);
  });

  $effect(() => {
    if (map && loaded && compare.mode === "voronoi" && compare.view === "fade") applyDifferenceFade(map, compare.sweep, compare.pair.a > compare.pair.b);
  });

  $effect(() => {
    // Voronoi tints a focused code's cells instead of outlining its land.
    const focus = compare.mode === "voronoi" ? null : compare.focus;
    if (map && loaded) applyFocus(map, compare.draws, focus, compare.view === "fade", compare.basemap === "satellite");
  });

  $effect(() => {
    if (map && loaded) applyOpacity(map, compare.draws, compare.opacities, compare.basemap === "satellite");
  });

  // Fade animates only while the map shows.
  $effect(() => {
    compare.animate(active && compare.view === "fade");
    return () => compare.animate(false);
  });

  // Each pick frames once, after the layout settles so a pane that just opened has its final size.
  function frame(target: Focus | ItemFocus | null) {
    if (!map || !loaded || !active || !target?.bbox || target === framed) return;
    framed = target;
    if (!target.fly) return;
    stopSpin();
    const [m, bbox] = [map, target.bbox as [number, number, number, number]];
    requestAnimationFrame(() => {
      m.resize();
      m.fitBounds(bbox, { padding: FOCUS_PAD, maxZoom: FOCUS_MAX_ZOOM });
    });
  }
  $effect(() => frame(compare.focus));

  $effect(() => {
    const voronoi = compare.mode === "voronoi";
    if (map && loaded) applyVoronoiFocus(map, compare.draws, voronoi ? compare.item : null, voronoi ? compare.focus : null);
  });

  $effect(() => frame(compare.item));

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
{#if compare.focus}
  <button class="focus" style:--inset="{inset}px" aria-label="Clear highlight" onclick={() => (compare.focus = null)}>{compare.focus.iso3} <span aria-hidden="true">×</span></button>
{:else if compare.item}
  <button class="focus" style:--inset="{inset}px" aria-label="Clear highlight" onclick={() => (compare.item = null)}>{compare.item.label} <span aria-hidden="true">×</span></button>
{/if}

<style>
  .map {
    flex: 1;
  }
  .map :global(.maplibregl-ctrl-bottom-right) {
    right: var(--inset);
    transition: right 300ms cubic-bezier(0.2, 0, 0, 1);
  }
  .focus {
    position: absolute;
    top: 0.75rem;
    left: calc((100% - var(--inset)) / 2);
    transform: translateX(-50%);
    transition: left 300ms cubic-bezier(0.2, 0, 0, 1);
    z-index: 3;
    padding: 0.3rem 0.75rem;
    border: 0;
    background: var(--cd-white);
    border-radius: 999px;
    box-shadow: var(--panel-shadow);
    color: inherit;
    font-family: inherit;
    font-size: 0.875rem;
    font-weight: 600;
    white-space: nowrap;
    cursor: pointer;
  }
  .focus span {
    margin-left: 0.25rem;
    color: var(--brand-grey--text);
  }
</style>
