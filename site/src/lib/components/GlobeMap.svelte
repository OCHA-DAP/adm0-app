<script lang="ts">
  import { untrack } from "svelte";
  import "maplibre-gl/dist/maplibre-gl.css";
  import * as maplibregl from "maplibre-gl";
  import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
  import { Protocol } from "pmtiles";
  import { SLOT_COLORS, type CompareState, type Hit } from "$lib/compare.svelte";
  import Swatch from "$lib/components/Swatch.svelte";
  import { LAYER_BY_ID } from "$lib/layers";
  import { createDrawMap, createOverlay, type DrawMap, type Overlay } from "$lib/map/maps";
  import { queryLayerId, type Draw } from "$lib/map/style";

  let { tilesBase, compare, active }: { tilesBase: string; compare: CompareState; active: boolean } = $props();

  // Apparent globe diameter in px at zoom 0 with the default camera, measured.
  const GLOBE_PX_AT_Z0 = 129;
  const GLOBE_FIT = 0.9;
  const SPIN_DEG_PER_S = 6;
  const CLICK_PAD = 3;

  maplibregl.setWorkerUrl(workerUrl);

  let container = $state<HTMLDivElement>();
  let overlayEl = $state<HTMLDivElement>();
  let main = $state.raw<DrawMap | null>(null);
  let overlay = $state.raw<Overlay | null>(null);
  let swipePct = $state(50);
  let lensAt = $state<{ x: number; y: number } | null>(null);

  const solo = $derived(compare.solo);
  const showOverlay = $derived(
    compare.stacked && solo !== "a" && (compare.view === "swipe" || lensAt !== null || solo === "b"),
  );
  const clip = $derived.by(() => {
    if (solo === "b") return "none";
    if (compare.view === "swipe") return `inset(0 0 0 ${swipePct}%)`;
    return lensAt ? `circle(${compare.lensRadius}px at ${lensAt.x}px ${lensAt.y}px)` : "circle(0px at 0 0)";
  });

  const clamp = (v: number) => Math.min(100, Math.max(0, v));

  function query(m: maplibregl.Map, draws: Draw[], point: maplibregl.Point): Hit[] {
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
    const dm = createDrawMap(el, tilesBase, untrack(() => compare.mainDraws), {
      center: [20, 10],
      zoom: fitZoom(),
      attributionControl: { compact: true },
    });
    const m = dm.map;
    m.on("click", (e) => {
      const all = [
        ...query(m, compare.mainDraws, e.point),
        ...(overlay && showOverlay ? query(overlay.map, compare.overlayDraws, e.point) : []),
      ];
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
    main = dm;
    return () => {
      stop.abort();
      untrack(() => overlay)?.destroy();
      overlay = null;
      dm.destroy();
      main = null;
      maplibregl.removeProtocol("pmtiles");
    };
  });

  $effect(() => {
    main?.setDraws(compare.mainDraws);
  });

  // Built on first use and kept, so switching between Swipe and Lens doesn't reload tiles.
  $effect(() => {
    if (compare.stacked && !overlay && main && overlayEl) {
      overlay = createOverlay(main.map, overlayEl, tilesBase, untrack(() => compare.overlayDraws));
    }
  });

  $effect(() => {
    overlay?.setDraws(compare.overlayDraws);
  });

  $effect(() => {
    overlay?.setActive(showOverlay);
  });

  $effect(() => {
    if (active) requestAnimationFrame(() => main?.map.resize());
  });

  function dragSwipe(e: PointerEvent) {
    if (!container || !(e.currentTarget as HTMLElement).hasPointerCapture(e.pointerId)) return;
    const rect = container.getBoundingClientRect();
    swipePct = clamp(((e.clientX - rect.left) / rect.width) * 100);
  }

  function swipeKeys(e: KeyboardEvent) {
    const by = { ArrowLeft: -2, ArrowRight: 2 }[e.key];
    if (by === undefined) return;
    e.preventDefault();
    swipePct = clamp(swipePct + by);
  }

  function trackLens(e: PointerEvent) {
    if (compare.view !== "lens" || !container) return;
    const rect = container.getBoundingClientRect();
    lensAt = { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }
</script>

<svelte:window onkeydown={(e) => active && compare.keydown(e)} onkeyup={(e) => compare.keyup(e)} />

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="map" bind:this={container} onpointermove={trackLens} onpointerleave={() => (lensAt = null)}></div>
<div class="overlay" class:hidden={!compare.stacked} bind:this={overlayEl} style:clip-path={clip} style:visibility={showOverlay ? "visible" : "hidden"}></div>
{#if compare.view === "swipe" && solo === null}
  <div
    class="divider"
    style:left="{swipePct}%"
    role="slider"
    tabindex="0"
    aria-label="Swipe position"
    aria-valuemin={0}
    aria-valuemax={100}
    aria-valuenow={Math.round(swipePct)}
    onpointerdown={(e) => (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)}
    onpointermove={dragSwipe}
    onkeydown={swipeKeys}
  >
    <span class="knob"><b style:color={SLOT_COLORS.a}>A</b><b style:color={SLOT_COLORS.b}>B</b></span>
  </div>
{/if}
{#if compare.view === "lens" && lensAt && solo === null}
  <div
    class="lens-ring"
    style:left="{lensAt.x - compare.lensRadius}px"
    style:top="{lensAt.y - compare.lensRadius}px"
    style:width="{compare.lensRadius * 2}px"
    style:height="{compare.lensRadius * 2}px"
  ></div>
{/if}
{#if compare.nowShowing}
  <div class="now-showing">
    <Swatch kind={compare.mode} color={compare.nowShowing.color} />{compare.nowShowing.label}
  </div>
{/if}

<style>
  .map {
    flex: 1;
  }
  .map :global(.maplibregl-control-container) {
    position: relative;
    z-index: 2;
  }
  .overlay {
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 1;
  }
  .divider {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2px;
    margin-left: -1px;
    background: var(--cd-grey--900);
    cursor: ew-resize;
    touch-action: none;
    z-index: 2;
  }
  .divider::before {
    content: "";
    position: absolute;
    inset: 0 -8px;
  }
  .knob {
    position: absolute;
    top: 50%;
    left: 50%;
    display: flex;
    gap: 0.6rem;
    padding: 0.25rem 0.5rem;
    transform: translate(-50%, -50%);
    background: var(--cd-white);
    border: 2px solid var(--cd-grey--900);
    border-radius: 999px;
    font-size: 0.75rem;
  }
  .lens-ring {
    position: absolute;
    border: 2px solid var(--cd-grey--900);
    border-radius: 50%;
    pointer-events: none;
    z-index: 2;
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
