<script lang="ts">
  import AttributesTable from "$lib/AttributesTable.svelte";
  import { CompareState } from "$lib/compare.svelte";
  import ComparePanel from "$lib/components/ComparePanel.svelte";
  import GlobeMap from "$lib/components/GlobeMap.svelte";
  import HitsPanel from "$lib/components/HitsPanel.svelte";
  import PasswordGate from "$lib/components/PasswordGate.svelte";

  let tilesBase = $state<string | null>(null);
  let tab = $state<"map" | "table">("map");
  // The table mounts on first visit and stays, keeping its data and filters.
  let tableSeen = $state(false);
  const compare = new CompareState();

  function show(next: "map" | "table") {
    tab = next;
    tableSeen ||= next === "table";
  }
</script>

{#if !tilesBase}
  <PasswordGate onunlock={(url) => (tilesBase = url)} />
{:else}
  <div class="app">
    <nav>
      <button class:active={tab === "map"} onclick={() => show("map")}>Map</button>
      <button class:active={tab === "table"} onclick={() => show("table")}>Names and attributes</button>
    </nav>
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
  nav {
    display: flex;
    border-bottom: 1px solid var(--cd-grey--400);
  }
  nav button {
    padding: 0.6rem 1rem;
    border: 0;
    border-bottom: 3px solid transparent;
    background: none;
    font-size: 0.875rem;
    cursor: pointer;
  }
  nav button.active {
    border-bottom-color: var(--cd-ocha-blue);
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
