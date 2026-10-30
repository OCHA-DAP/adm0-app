<script lang="ts">
  import { MODES, SLOT_COLORS, VIEWS, type CompareState, type Kind, type View } from "$lib/compare.svelte";
  import Swatch from "$lib/components/Swatch.svelte";
  import { LAYERS } from "$lib/layers";

  let { compare }: { compare: CompareState } = $props();

  const groups = [...new Set(LAYERS.map((l) => l.group))];
</script>

{#snippet segmented(label: string, options: { id: string; label: string }[], current: string, pick: (id: string) => void, keyed = false)}
  <div class="segmented" role="radiogroup" aria-label={label}>
    {#each options as o, i (o.id)}
      <button role="radio" aria-checked={current === o.id} class:active={current === o.id} title={keyed ? `Press ${i + 1}` : undefined} onclick={() => pick(o.id)}>{o.label}</button>
    {/each}
  </div>
{/snippet}

{#snippet options()}
  {#each groups as group (group)}
    {@const layers = compare.kindLayers.filter((l) => l.group === group)}
    {#if layers.length}
      <optgroup label={group}>
        {#each layers as layer (layer.id)}
          <option value={layer.id}>{layer.label}</option>
        {/each}
      </optgroup>
    {/if}
  {/each}
{/snippet}

<div class="panel">
  {@render segmented("Compare", MODES, compare.mode, (id) => compare.setMode(id as Kind))}
  <h2>View</h2>
  {@render segmented("View", VIEWS, compare.view, (id) => compare.setView(id as View), true)}
  <p class="hint">{compare.viewInfo.hint} Press 1 to 3 to switch views.</p>
  {#if compare.view === "single"}
    <h2>Source</h2>
    <label class="slot">
      <Swatch kind={compare.mode} color={compare.singleLayer.color} />
      <select bind:value={compare.single[compare.mode]}>{@render options()}</select>
    </label>
    <p class="hint">Press [ or ] to step through sources.</p>
  {:else}
    <h2>Compare</h2>
    {#each ["a", "b"] as const as slot (slot)}
      <label class="slot">
        <span class="badge" style:--color={SLOT_COLORS[slot]}>{slot.toUpperCase()}</span>
        <Swatch kind={compare.mode} color={SLOT_COLORS[slot]} />
        <select bind:value={compare.pairs[compare.mode][slot]}>{@render options()}</select>
      </label>
    {/each}
    <button class="btn swap" onclick={() => compare.swap()}>Swap A and B</button>
    <p class="hint">Tap [ or ] to show only A or B, or hold to peek. Shift+[ or ] changes B.</p>
  {/if}
  {#if compare.hits.length === 0}
    <p class="hint">Click the map to see what each source says at that point.</p>
  {/if}
</div>

<style>
  .panel {
    left: 0.75rem;
    width: 17rem;
  }
  .segmented {
    display: flex;
    border: 1px solid var(--cd-grey--500);
    border-radius: var(--brand-radius--sm);
    overflow: hidden;
    background: var(--cd-white);
  }
  .segmented button {
    flex: 1 1 0;
    padding: 0.3rem 0.6rem;
    border: none;
    border-left: 1px solid var(--cd-grey--400);
    background: var(--cd-white);
    color: var(--cd-grey--800);
    font-size: 0.75rem;
    font-weight: 500;
    cursor: pointer;
  }
  .segmented button:first-child {
    border-left: none;
  }
  .segmented button:hover:not(.active) {
    background: var(--cd-grey--300);
  }
  .segmented button.active {
    background: var(--brand-primary--text);
    color: var(--cd-white);
  }
  .hint {
    color: var(--cd-grey--700);
    font-size: 0.75rem;
    line-height: 1.4;
    margin: 0.75rem 0 0;
  }
  .slot {
    display: flex;
    align-items: center;
    gap: 0.3rem;
    margin: 0.35rem 0;
  }
  .slot select {
    flex: 1;
    min-width: 0;
  }
  .swap {
    margin: 0.2rem 0 0.4rem;
  }
</style>
