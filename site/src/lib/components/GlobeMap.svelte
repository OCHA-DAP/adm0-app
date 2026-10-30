<script lang="ts">
  import { untrack } from "svelte";
  import "maplibre-gl/dist/maplibre-gl.css";
  import * as maplibregl from "maplibre-gl";
  import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
  import { Protocol } from "pmtiles";
  import type { CompareState, Hit } from "$lib/compare.svelte";
  import Swatch from "$lib/components/Swatch.svelte";
  import { LAYER_BY_ID } from "$lib/layers";
  import { applyDraws, buildStyle, queryLayerId } from "$lib/map/style";

  let { tilesBase, compare, active }: { tilesBase: string; compare: CompareState; active: boolean } = $props();

  // Apparent globe diameter in px at zoom 0 with the default camera, measured.
  const GLOBE_PX_AT_Z0 = 129;
  const GLOBE_FIT = 0.9;
  const SPIN_DEG_PER_S = 6;
  const CLICK_PAD = 3;

  maplibregl.setWorkerUrl(workerUrl);

  let container = $state<HTMLDivElement>();
  let map = $state.raw<maplibregl.Map | null>(null);
  let loaded = $state(false);

  function query(m: maplibregl.Map, point: maplibregl.Point): Hit[] {
    const draws = compare.draws;
    const features = m.queryRenderedFeatures(
      [
        [point.x - CLICK_PAD, point.y - CLICK_PAD],
        [point.x + CLICK_PAD, point.y + CLICK_PAD],
      ],
      { layers: draws.map((d) => queryLayerId(d.id)) },
    );
    return features.flatMap((f) => {
      const draw = draws.find((d) => d.id === f.sourceLayer);
      if (!draw) return [];
      return [{ slot: draw.slot ?? null, label: LAYER_BY_ID.get(draw.id)!.label, color: draw.color, properties: f.properties }];
    });
  }

  $effect(() => {
    if (!container) return;
    const protocol = new Protocol();
    maplibregl.addProtocol("pmtiles", protocol.tile);
    const el = container;
    const fitZoom = () => Math.log2((GLOBE_FIT * Math.min(el.clientWidth, el.clientHeight)) / GLOBE_PX_AT_Z0);
    const m = new maplibregl.Map({
      container: el,
      style: buildStyle(tilesBase, untrack(() => compare.draws)),
      center: [20, 10],
      zoom: fitZoom(),
      attributionControl: { compact: true },
    });
    m.once("load", () => (loaded = true));
    m.on("click", (e) => {
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
    frame = requestAnimationFrame(spin);
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
    map = m;
    return () => {
      stop.abort();
      m.remove();
      map = null;
      loaded = false;
      maplibregl.removeProtocol("pmtiles");
    };
  });

  $effect(() => {
    if (map && loaded) applyDraws(map, compare.draws);
  });

  $effect(() => {
    if (active) requestAnimationFrame(() => map?.resize());
  });
</script>

<svelte:window onkeydown={(e) => active && compare.keydown(e)} onkeyup={(e) => compare.keyup(e)} />

<div class="map" bind:this={container}></div>
{#if compare.nowShowing}
  <div class="now-showing">
    <Swatch kind={compare.mode} color={compare.nowShowing.color} />{compare.nowShowing.label}
  </div>
{/if}

<style>
  .map {
    flex: 1;
  }
  .now-showing {
    position: absolute;
    top: 0.75rem;
    left: 50%;
    transform: translateX(-50%);
    padding: 0.3rem 0.75rem;
    background: var(--cd-white);
    border-radius: 999px;
    box-shadow: var(--panel-shadow);
    font-size: 0.875rem;
    font-weight: 600;
    pointer-events: none;
    z-index: 3;
  }
</style>
