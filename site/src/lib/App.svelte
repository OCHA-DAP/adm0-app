<script lang="ts">
  import AttributesTable from "$lib/AttributesTable.svelte";
  import { CompareState } from "$lib/compare.svelte";
  import ComparePanel from "$lib/components/ComparePanel.svelte";
  import GlobeMap from "$lib/components/GlobeMap.svelte";
  import HitsPanel from "$lib/components/HitsPanel.svelte";
  import PasswordGate from "$lib/components/PasswordGate.svelte";

  let tilesBase = $state<string | null>(null);
  const startTab = new URLSearchParams(import.meta.env.DEV ? location.search : "").get("tab") === "table" ? "table" : "map";
  let tab = $state<"map" | "table">(startTab);
  // The table mounts on first visit and stays, keeping its data and filters.
  let tableSeen = $state(startTab === "table");
  const compare = new CompareState();

  // View state lives in the URL in dev only; written after unlock so the password page URL stays bare.
  $effect(() => {
    if (!tilesBase || !import.meta.env.DEV) return;
    const url = new URL(location.href);
    url.searchParams.set("tab", tab);
    compare.writeParams(url.searchParams);
    history.replaceState(null, "", url);
  });

  function show(next: "map" | "table") {
    tab = next;
    tableSeen ||= next === "table";
  }
</script>

{#if !tilesBase}
  <PasswordGate onunlock={(url) => (tilesBase = url)} />
{:else}
  <div class="app">
    <header class="bar">
      <span class="title">Boundary comparison</span>
      <nav aria-label="Views">
        <button aria-current={tab === "map" ? "page" : undefined} onclick={() => show("map")}>Map</button>
        <button aria-current={tab === "table" ? "page" : undefined} onclick={() => show("table")}>Names and attributes</button>
      </nav>
    </header>
    <div class="view" class:hidden={tab !== "map"}>
      <GlobeMap {tilesBase} {compare} active={tab === "map"} />
      <ComparePanel {compare} />
      <HitsPanel {compare} />
    </div>
    {#if tableSeen}
      <div class="view" class:hidden={tab !== "table"}><AttributesTable {tilesBase} /></div>
    {/if}
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
    display: flex;
    gap: 1.75rem;
  }
  nav button {
    padding: 0;
    border: 0;
    background: none;
    color: var(--cd-grey--800);
    font-size: 0.95rem;
    white-space: nowrap;
    cursor: pointer;
  }
  nav button:hover {
    color: var(--brand-primary--dark);
  }
  nav button[aria-current="page"] {
    color: var(--brand-primary--text);
    font-weight: 600;
  }
  .view {
    display: flex;
    flex: 1;
    min-height: 0;
    position: relative;
  }
  .view > :global(.table-view) {
    flex: 1;
    min-width: 0;
  }
</style>
