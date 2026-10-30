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
  <p class="hint">{compare.viewInfo.hint} Press 1 to 4 to switch views.</p>
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
        <Swatch kind={compare.mode} color={SLOT_COLORS[slot]} dashed={slot === "b"} />
        <select bind:value={compare.pairs[compare.mode][slot]}>{@render options()}</select>
      </label>
    {/each}
    <button class="swap" onclick={() => compare.swap()}>Swap A and B</button>
    {#if compare.view === "overlay"}
      <label class="range">
        <span>A</span>
        <input type="range" min="0" max="1" step="0.05" bind:value={compare.fade} aria-label="Crossfade between A and B" />
        <span>B</span>
      </label>
      <label class="check">
        <input type="checkbox" checked={compare.blinking} onchange={(e) => compare.setBlinking(e.currentTarget.checked)} />
        Blink between A and B
      </label>
    {:else if compare.view === "lens"}
      <label class="range">
        <span>Lens</span>
        <input type="range" min="40" max="300" step="10" bind:value={compare.lensRadius} aria-label="Lens size" />
      </label>
    {/if}
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
    border: 1px solid var(--cd-ocha-blue);
    border-radius: 4px;
    overflow: hidden;
  }
  .segmented button {
    flex: 1;
    padding: 0.35rem;
    border: 0;
    background: none;
    color: var(--cd-ocha-blue);
    font-size: 0.8125rem;
    cursor: pointer;
  }
  .segmented button.active {
    background: var(--cd-ocha-blue);
    color: var(--cd-white);
  }
  .hint {
    color: var(--brand-grey--text);
    margin: 0.75rem 0 0;
  }
  .slot {
    display: flex;
    align-items: center;
    gap: 0.3rem;
    margin: 0.3rem 0;
  }
  .slot select {
    flex: 1;
    min-width: 0;
    font-size: 0.8125rem;
  }
  .swap {
    margin: 0.2rem 0 0.4rem;
    padding: 0.2rem 0.5rem;
    border: 1px solid var(--cd-grey--400);
    border-radius: 4px;
    background: none;
    font-size: 0.75rem;
    cursor: pointer;
  }
  .range,
  .check {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin-top: 0.4rem;
  }
  .range input {
    flex: 1;
  }
</style>
