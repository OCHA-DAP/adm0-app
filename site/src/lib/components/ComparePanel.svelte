<script lang="ts">
  import { BASEMAPS, MODES, SLOT_COLORS, VIEWS, type Basemap, type CompareState, type Kind, type View } from "$lib/compare.svelte";
  import Segmented from "$lib/components/Segmented.svelte";

  let { compare }: { compare: CompareState } = $props();
</script>

{#snippet matrix(slots: { id: string; color: string; current: string; pick: (id: string) => void }[])}
  <table class="matrix">
    <thead><tr><th></th>{#each slots as s (s.id)}<th><span class="badge" style:--color={s.color}>{s.id.toUpperCase()}</span></th>{/each}</tr></thead>
    <tbody>
      {#each compare.kindLayers as layer (layer.id)}
        <tr>
          <td>{layer.label}</td>
          {#each slots as s (s.id)}
            <td><input type="radio" name="src-{s.id}" style:accent-color={s.color} checked={s.current === layer.source} onchange={() => s.pick(layer.source)} aria-label="{s.id.toUpperCase()}: {layer.label}" /></td>
          {/each}
        </tr>
      {/each}
      {#if compare.mode === "voronoi"}
        <tr class="fixed"><td>OpenStreetMap</td><td colspan={slots.length}><span class="swatch"></span></td></tr>
      {/if}
    </tbody>
  </table>
{/snippet}

<div class="panel">
  <h2>Basemap</h2>
  <Segmented stretch label="Basemap" options={BASEMAPS} current={compare.basemap} pick={(id) => (compare.basemap = id as Basemap)} />
  <h2>Geometry</h2>
  <Segmented stretch label="Geometry" options={MODES} current={compare.mode} pick={(id) => compare.setMode(id as Kind)} />
  <h2>View</h2>
  <Segmented stretch label="View" options={VIEWS} current={compare.view} pick={(id) => compare.setView(id as View)} />
  <h2>Compare</h2>
  {@render matrix((["a", "b"] as const).map((slot) => ({ id: slot, color: SLOT_COLORS[slot], current: compare.pair[slot], pick: (id: string) => (compare.pair[slot] = id) })))}
  <p class="hint">Press [ or ] to switch views.</p>
</div>

<style>
  .panel {
    left: 0.75rem;
    width: 17rem;
  }
  h2:first-child {
    margin-top: 0;
  }
  .hint {
    color: var(--cd-grey--700);
    font-size: 0.75rem;
    line-height: 1.4;
    margin: 0.75rem 0 0;
  }
  .swatch {
    display: inline-block;
    width: 0.8rem;
    height: 0.8rem;
    vertical-align: middle;
    border: 1px solid #424242;
    border-radius: 2px;
    background: rgb(66 66 66 / 0.85);
  }
  .matrix {
    width: 100%;
    margin: 0.35rem 0;
    border-collapse: collapse;
    font-size: 0.75rem;
  }
  .matrix td,
  .matrix th {
    padding: 0.15rem 0.25rem;
  }
  .matrix td:first-child {
    width: 100%;
  }
  .matrix td:not(:first-child),
  .matrix th {
    width: 1.75rem;
    text-align: center;
  }
  .matrix tbody tr:not(.fixed):hover {
    background: var(--cd-grey--300);
  }
</style>
