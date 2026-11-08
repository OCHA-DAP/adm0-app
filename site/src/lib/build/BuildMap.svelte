<script lang="ts">
  import "maplibre-gl/dist/maplibre-gl.css";
  import * as maplibregl from "maplibre-gl";
  import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
  import { Protocol } from "pmtiles";
  import type { ExpressionSpecification, StyleSpecification } from "maplibre-gl";
  import { SLOT_COLORS, type Hit } from "$lib/compare.svelte";
  import { catalogPath } from "$lib/layers";
  import { SATELLITE, SATELLITE_PROTOCOL, satelliteTile } from "$lib/map/satellite";
  import { LINE_DASH, LINE_WIDTHS, applyBasemap, globeFitZoom } from "$lib/map/style";
  import positron from "$lib/utils/basemap/positron.json";

  let {
    change,
    bbox,
    overview,
    tilesBase,
    compare,
    stepChanges,
    parents,
    labels,
    cells,
    legend,
    border,
    sweep,
    satellite,
    hasCells,
    onpick,
  }: {
    change: string | null;
    bbox: number[] | null;
    overview: number[] | null;
    tilesBase: string;
    compare: string[] | null;
    stepChanges: string[];
    parents: number[];
    labels: string[];
    cells: string[];
    legend: string[];
    border: string[] | null;
    sweep: number;
    satellite: boolean;
    hasCells: boolean;
    onpick: (hits: Hit[]) => void;
  } = $props();

  const FRAME_PAD = 80;
  const ROW_MAX_ZOOM = 14;
  const OVERVIEW_ZOOM_MS = 2000;
  const SELECTED_FIRST = -1e9;
  const NOTHING: ExpressionSpecification = ["literal", false];
  const SLOTS = ["a", "b"] as const;
  const STEP_OUTPUTS: Record<string, string> = $derived({
    gaul_l0: `${tilesBase}/${catalogPath("gaul_l0")}`,
    gaul_voronoi: `${tilesBase}/${catalogPath("gaul_voronoi")}`,
    build_un: "/build/build_un.pmtiles",
    build_path_errors: "/build/build_path_errors.pmtiles",
    build_path_disputed: "/build/build_path_disputed.pmtiles",
    build_gaul: "/build/build_gaul.pmtiles",
  });
  const PATCH_OPACITY = 0.45;
  const PARENT_OPACITY = 0.3;
  const CHANGE_OPACITY = 0.7;

  function hasChange(id: string): ExpressionSpecification {
    return ["in", ["literal", `;${id};`], ["concat", ";", ["coalesce", ["get", "change_ids"], ""], ";"]];
  }

  function borderPatches([x, y]: string[]): ExpressionSpecification {
    const pairOf = (a: string, b: string): ExpressionSpecification => ["all", ["==", ["get", "a_code"], a], ["==", ["get", "b_code"], b]];
    return ["any", pairOf(x, y), pairOf(y, x)];
  }

  maplibregl.setWorkerUrl(workerUrl);
  let container = $state<HTMLDivElement>();
  let map = $state.raw<maplibregl.Map | null>(null);
  let loaded = $state(false);

  $effect(() => {
    if (!container) return;
    const protocol = new Protocol();
    maplibregl.addProtocol("pmtiles", protocol.tile);
    maplibregl.addProtocol(SATELLITE_PROTOCOL, satelliteTile);
    const m = new maplibregl.Map({ container, style: { ...positron, projection: { type: "globe" }, transition: { duration: 0, delay: 0 } } as StyleSpecification, center: [20, 15], zoom: globeFitZoom(container), hash: import.meta.env.DEV });
    m.once("load", () => {
      m.addSource("satellite", SATELLITE);
      m.addLayer({ id: "satellite", type: "raster", source: "satellite", layout: { visibility: "none" } });
      m.addSource("build_units", { type: "vector", url: "pmtiles:///build/build_units.pmtiles" });
      for (const [id, url] of Object.entries(STEP_OUTPUTS)) m.addSource(id, { type: "vector", url: `pmtiles://${url}` });
      const units = { source: "build_units", "source-layer": "build_units", filter: NOTHING } as const;
      m.addLayer({ id: "parents", type: "fill", source: "build_un", "source-layer": "build_un", filter: NOTHING, paint: { "fill-color": SLOT_COLORS.a, "fill-opacity": PARENT_OPACITY } });
      m.addLayer({ ...units, id: "step-changes", type: "fill", paint: { "fill-color": SLOT_COLORS.b } });
      m.addLayer({ ...units, id: "focus", type: "line", paint: { "line-color": SLOT_COLORS.b, "line-width": 3 } });
      m.addSource("build_line_patches", { type: "vector", url: "pmtiles:///build/build_line_patches.pmtiles" });
      for (const slot of SLOTS) {
        m.addLayer({ id: `patch-${slot}`, type: "fill", source: "build_line_patches", "source-layer": "build_line_patches", filter: NOTHING, paint: { "fill-color": SLOT_COLORS[slot] } });
      }
      for (const id of Object.keys(STEP_OUTPUTS)) {
        m.addLayer({ id: `pick-${id}`, type: "fill", source: id, "source-layer": id, layout: { visibility: "none" }, paint: { "fill-opacity": 0 } });
        m.addLayer({ id: `output-${id}`, type: "line", source: id, "source-layer": id, layout: { visibility: "none" }, paint: { "line-width": LINE_WIDTHS, "line-dasharray": LINE_DASH } });
      }
      // Stage 08 writes no island tiles when the automatic check finds nothing.
      if (hasCells) {
        m.addSource("build_cell_islands", { type: "vector", url: "pmtiles:///build/build_cell_islands.pmtiles" });
        const islands = { source: "build_cell_islands", "source-layer": "build_cell_islands", filter: NOTHING } as const;
        m.addLayer({ ...islands, id: "cell-islands", type: "fill", paint: { "fill-color": SLOT_COLORS.b, "fill-opacity": CHANGE_OPACITY } });
        m.addLayer({ ...islands, id: "cell-focus", type: "line", paint: { "line-color": SLOT_COLORS.b, "line-width": 3 } });
      }
      m.addSource("labels", { type: "geojson", data: "/build/labels.geojson" });
      m.addLayer({ id: "unit-labels", type: "symbol", source: "labels", filter: NOTHING, layout: { "text-field": ["get", "text"], "text-font": ["Noto Sans Bold"], "text-size": 13, "text-padding": 24 }, paint: { "text-color": "#333333", "text-halo-color": "#FFFFFF", "text-halo-width": 2 } });
      loaded = true;
    });
    m.on("click", (e) => {
      if (!compare) return;
      onpick(
        SLOTS.flatMap((slot, i) => {
          const properties = m.queryRenderedFeatures(e.point, { layers: [`pick-${compare[i]}`] })[0]?.properties;
          return properties ? [{ slot: null, label: legend[i], color: SLOT_COLORS[slot], properties }] : [];
        }),
      );
    });
    if (import.meta.env.DEV) Object.assign(window, { map: m });
    map = m;
    return () => {
      m.remove();
      map = null;
      loaded = false;
      maplibregl.removeProtocol("pmtiles");
      maplibregl.removeProtocol(SATELLITE_PROTOCOL);
    };
  });

  $effect(() => {
    if (!map || !loaded) return;
    map.setFilter("focus", change ? hasChange(change) : NOTHING);
    map.setFilter("parents", parents.length ? ["in", ["get", "objectid"], ["literal", parents]] : NOTHING);
    map.setFilter("step-changes", stepChanges.length ? ["any", ...stepChanges.map(hasChange)] : NOTHING);
    if (!hasCells) return;
    map.setFilter("cell-islands", ["in", ["get", "change_id"], ["literal", cells]]);
    map.setFilter("cell-focus", ["==", ["get", "change_id"], change ?? ""]);
  });

  $effect(() => {
    if (!map || !loaded) return;
    map.setFilter("unit-labels", ["in", ["get", "change"], ["literal", labels]]);
    map.setLayoutProperty("unit-labels", "symbol-sort-key", ["case", ["==", ["get", "change"], change ?? ""], SELECTED_FIRST, ["-", 0, ["get", "km2"]]]);
  });

  $effect(() => {
    if (!map || !loaded) return;
    for (const id of Object.keys(STEP_OUTPUTS)) {
      const visibility = compare?.includes(id) ? "visible" : "none";
      map.setLayoutProperty(`output-${id}`, "visibility", visibility);
      map.setLayoutProperty(`pick-${id}`, "visibility", visibility);
    }
    SLOTS.forEach((slot, i) => {
      if (compare) map!.setPaintProperty(`output-${compare[i]}`, "line-color", SLOT_COLORS[slot]);
      map!.setFilter(`patch-${slot}`, border ? borderPatches(border) : NOTHING);
    });
  });

  $effect(() => {
    if (!map || !loaded) return;
    map.setPaintProperty("step-changes", "fill-opacity", CHANGE_OPACITY * sweep);
    map.setPaintProperty("focus", "line-opacity", sweep);
    SLOTS.forEach((slot, i) => {
      const opacity = slot === "a" ? 1 - sweep : sweep;
      if (compare) map!.setPaintProperty(`output-${compare[i]}`, "line-opacity", opacity);
      map!.setPaintProperty(`patch-${slot}`, "fill-opacity", PATCH_OPACITY * opacity);
    });
  });

  $effect(() => {
    if (map && loaded) applyBasemap(map, satellite);
  });

  $effect(() => {
    if (!map || !loaded || !bbox) return;
    const m = map;
    const frame = (box: number[], duration?: number) => m.fitBounds(box as [number, number, number, number], { padding: FRAME_PAD, maxZoom: ROW_MAX_ZOOM, duration });
    const zoomOut = () => frame(overview!, OVERVIEW_ZOOM_MS);
    // Stopping first keeps the interrupted move's moveend from starting the zoom out early.
    m.stop();
    if (overview) m.once("moveend", zoomOut);
    frame(bbox);
    return () => m.off("moveend", zoomOut);
  });
</script>

<div class="map" bind:this={container}></div>

<style>
  .map {
    flex: 1;
    min-width: 0;
  }
</style>
