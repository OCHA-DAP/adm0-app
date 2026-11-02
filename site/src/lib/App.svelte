<script lang="ts">
  import { untrack } from "svelte";
  import AttributesTable from "$lib/AttributesTable.svelte";
  import { CompareState, type View } from "$lib/compare.svelte";
  import ComparePanel from "$lib/components/ComparePanel.svelte";
  import GlobeMap from "$lib/components/GlobeMap.svelte";
  import HitsPanel from "$lib/components/HitsPanel.svelte";
  import PasswordGate from "$lib/components/PasswordGate.svelte";
  import { itemTitle, listOf, mergeItems, prepareItems, unionBox, type AttributeRow, type GeometryList, type ItemRow, type Part } from "$lib/attributes";
  import { layerFor } from "$lib/layers";

  type Tab = "map" | "split" | "table";
  const TABS: { id: Tab; label: string }[] = [
    { id: "map", label: "Map" },
    { id: "split", label: "Geometry" },
    { id: "table", label: "Attributes" },
  ];

  let tilesBase = $state<string | null>(null);
  const startTab = TABS.find((t) => t.id === new URLSearchParams(import.meta.env.DEV ? location.search : "").get("tab"))?.id ?? "map";
  let tab = $state<Tab>(startTab);
  const compare = new CompareState();
  let rows = $state.raw<AttributeRow[]>([]);
  let items = $state.raw<ItemRow[]>([]);
  const merged = $derived(mergeItems(items, compare.pair.a, compare.pair.b));
  // The map draws only the differences the Geometry pane lists, and both kinds otherwise.
  let list = $state<GeometryList>("islands");
  const diffKind = $derived(tab !== "split" ? null : list === "islands" ? "island" : "land");
  let failed = $state(false);

  $effect(() => {
    if (!tilesBase) return;
    const load = (name: string) => fetch(`${tilesBase}/${name}`).then((r) => (r.ok ? r.json() : Promise.reject(r.status)));
    load("attributes.json")
      .then((data: AttributeRow[]) => (rows = data))
      .catch(() => (failed = true));
    load("items.json")
      .then((data: ItemRow[]) => (items = prepareItems(data)))
      .catch(() => (items = []));
  });

  // View state lives in the URL in dev only; written after unlock so the password page URL stays bare.
  $effect(() => {
    if (!tilesBase || !import.meta.env.DEV) return;
    const url = new URL(location.href);
    url.searchParams.set("tab", tab);
    compare.writeParams(url.searchParams);
    history.replaceState(null, "", url);
  });

  function show(next: Tab) {
    tab = next;
    // Click results belong to the Map tab; Geometry clicks pick codes and differences.
    if (next !== "map") compare.hits = [];
  }

  // The table pane's width in Geometry, which the map pads its camera by.
  const PANE_REM = 36;
  const inset = $derived(tab === "map" ? 0 : PANE_REM * parseFloat(getComputedStyle(document.documentElement).fontSize));

  // The highlight slides under the current tab.
  const tabButtons: HTMLButtonElement[] = [];
  let pill = $state({ left: 0, width: 0 });
  function placePill() {
    const b = tabButtons[TABS.findIndex((t) => t.id === tab)];
    if (b) pill = { left: b.offsetLeft, width: b.offsetWidth };
  }
  $effect(() => {
    if (!tilesBase) return;
    void tab;
    placePill();
    document.fonts.ready.then(placePill);
  });

  const drawn = $derived((["a", "b"] as const).map((slot) => layerFor(compare.pair[slot], "polygon").id));

  // Sources can share a code for different places, so frame only the shown sources' parts.
  function shownBox(row: AttributeRow): number[] | null {
    const layers = compare.view === "a" ? [drawn[0]] : compare.view === "b" ? [drawn[1]] : drawn;
    const boxes = (row.parts ?? []).filter((p) => layers.includes(p.layer)).map((p) => p.bbox);
    if (!boxes.length) return row.bbox;
    return unionBox(boxes);
  }

  // A code restored from a dev URL has no bbox until the rows arrive.
  $effect(() => {
    const restored = compare.focus;
    if (!restored || restored.bbox || !rows.length) return;
    const row = rows.find((r) => r.iso3 === restored.iso3);
    const bbox = row && shownBox(row);
    // A code with no geometry stays unframed; refocusing it with a null bbox would retrigger this effect.
    if (bbox) compare.focusOn(restored.iso3, bbox, [], false);
  });

  function focus(row: AttributeRow, parts: Part[] = [], fly = true) {
    compare.focusOn(row.iso3, shownBox(row), parts, fly);
    if (tab === "table") show("split");
  }

  // A picked part shows its source alone, and a difference or a code in Voronoi shows in Fade;
  // the view picked before them returns once the table's pick is cleared.
  let viewBefore: View | null = null;
  function borrowView(next: View) {
    viewBefore ??= compare.view;
    compare.setView(next);
  }
  function restoreView() {
    if (!viewBefore) return;
    const back = viewBefore;
    viewBefore = null;
    untrack(() => compare.setView(back));
  }
  $effect(() => {
    if (!compare.item && !compare.focus) restoreView();
  });

  // A focused difference of the other kind clears when the list switches.
  $effect(() => {
    const kind = list;
    untrack(() => {
      const row = compare.item && merged.find((it) => it.item === compare.item!.ids[0]);
      if (row && listOf(row.type) !== kind) compare.item = null;
    });
  });

  function focusFromTable(row: AttributeRow) {
    if (compare.mode === "voronoi") borrowView("fade");
    else restoreView();
    focus(row);
  }

  function focusItem(row: ItemRow, label: string) {
    borrowView("fade");
    compare.focusItem(row, label);
    if (tab === "table") show("split");
  }

  function pickItem(id: string | null) {
    const row = id ? merged.find((it) => it.items?.includes(id)) : null;
    if (!row || (diffKind && listOf(row.type) !== list)) {
      compare.item = null;
      return;
    }
    borrowView("fade");
    compare.focusItem(row, itemTitle(row), false);
  }

  // A map click narrows to the clicked feature only when its source splits the code.
  function pick(iso3: string, layer: string, name: string) {
    const row = rows.find((r) => r.iso3 === iso3);
    if (!row) return;
    const own = (row.parts ?? []).filter((p) => p.layer === layer);
    const part = own.length > 1 ? (own.find((p) => p.name === name) ?? null) : null;
    // A click inside the focused code keeps its picked part unless it lands on another one.
    if (!part && compare.focus?.iso3 === iso3) return;
    focus(row, part ? [part] : [], false);
  }
</script>

{#if !tilesBase}
  <PasswordGate onunlock={(url) => (tilesBase = url)} />
{:else}
  <div class="app">
    <header class="bar">
      <span class="title">Boundary comparison</span>
      <nav aria-label="Views">
        <span class="pill" style:transform="translateX({pill.left}px)" style:width="{pill.width}px"></span>
        {#each TABS as t, i (t.id)}
          <button bind:this={tabButtons[i]} aria-current={tab === t.id ? "page" : undefined} onclick={() => show(t.id)}>{t.label}</button>
        {/each}
      </nav>
    </header>
    <div class="views" style:--pane="{PANE_REM}rem" style:--shift={tab === "map" ? "100%" : tab === "split" ? `calc(100% - ${PANE_REM}rem)` : "0%"}>
      <div class="view map">
        <GlobeMap {tilesBase} {compare} active={tab !== "table"} hits={tab === "map"} {inset} {diffKind} onpick={pick} onitempick={pickItem} />
        <HitsPanel {compare} {inset} />
        <ComparePanel {compare} />
      </div>
      <div class="view table" class:open={tab !== "map"}>
        <div class="slide" class:full={tab === "table"}>
          <AttributesTable {rows} items={merged} {failed} focus={compare.focus} item={compare.item} pair={compare.pair} split={tab === "split"} bind:list onfocus={focusFromTable} onitem={focusItem} />
        </div>
      </div>
    </div>
  </div>
{/if}

<style>
  .app {
    display: flex;
    flex-direction: column;
    height: 100vh;
  }
  .bar {
    display: flex;
    flex-shrink: 0;
    gap: 1rem;
    justify-content: space-between;
    align-items: center;
    height: 3.5rem;
    padding: 0 1.5rem;
    background: var(--cd-white);
    border-bottom: 1px solid var(--brand-grey--border);
  }
  .title {
    font-family: var(--brand-font-heading);
    font-size: 1.125rem;
    font-weight: 700;
    color: var(--brand-primary--text);
  }
  nav {
    position: relative;
    display: flex;
    padding: 3px;
    border-radius: 999px;
    background: var(--cd-grey--300);
  }
  .pill {
    position: absolute;
    top: 3px;
    bottom: 3px;
    left: 0;
    border-radius: 999px;
    background: var(--brand-primary--text);
    transition:
      transform 250ms cubic-bezier(0.2, 0, 0, 1),
      width 250ms cubic-bezier(0.2, 0, 0, 1);
  }
  nav button {
    position: relative;
    padding: 0.3rem 0.9rem;
    border: 0;
    background: none;
    color: var(--cd-grey--800);
    font-size: 0.85rem;
    font-weight: 500;
    white-space: nowrap;
    cursor: pointer;
    transition: color 250ms;
  }
  nav button:hover:not([aria-current]) {
    color: var(--brand-primary--dark);
  }
  nav button[aria-current="page"] {
    color: var(--cd-white);
  }
  .views {
    position: relative;
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }
  /* Keeps the map's floating panels beneath the sliding table. */
  .view {
    display: flex;
    flex: 1;
    min-width: 0;
    min-height: 0;
  }
  .view.map {
    position: absolute;
    inset: 0;
    isolation: isolate;
  }
  /* The table pane slides over the full-width map with a transform, so nothing re-lays out mid-slide. */
  .view.table {
    position: absolute;
    inset: 0;
    background: var(--cd-white);
    transform: translateX(var(--shift));
    transition: transform 300ms cubic-bezier(0.2, 0, 0, 1);
    will-change: transform;
  }
  .view.table.open {
    border-left: 1px solid var(--cd-grey--400);
  }
  .slide {
    display: flex;
    width: var(--pane);
  }
  .slide.full {
    width: 100%;
  }
  @media (prefers-reduced-motion: reduce) {
    .pill,
    .view.table {
      transition: none;
    }
  }
  .slide > :global(.table-view) {
    flex: 1;
    min-width: 0;
  }
</style>
