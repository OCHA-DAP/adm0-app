<script lang="ts">
  import { MODES, SLOT_COLORS, VIEWS, type CompareState, type Kind, type View } from "$lib/compare.svelte";

  let { compare }: { compare: CompareState } = $props();
</script>

{#snippet segmented(label: string, options: { id: string; label: string }[], current: string, pick: (id: string) => void, keyed = false)}
  <div class="segmented" role="radiogroup" aria-label={label}>
    {#each options as o, i (o.id)}
      <button role="radio" aria-checked={current === o.id} class:active={current === o.id} title={keyed ? `Press ${i + 1}` : undefined} onclick={() => pick(o.id)}>{o.label}</button>
    {/each}
  </div>
{/snippet}

{#snippet matrix(slots: { id: string; color: string; current: string; pick: (id: string) => void }[])}
  <table class="matrix">
    {#if slots.length > 1}
      <thead><tr><th></th>{#each slots as s (s.id)}<th><span class="badge" style:--color={s.color}>{s.id.toUpperCase()}</span></th>{/each}</tr></thead>
    {/if}
    <tbody>
      {#each compare.kindLayers as layer (layer.id)}
        <tr>
          <td>{layer.label}</td>
          {#each slots as s (s.id)}
            <td><input type="radio" name="src-{s.id}" style:accent-color={s.color} checked={s.current === layer.id} onchange={() => s.pick(layer.id)} aria-label="{s.id.toUpperCase()}: {layer.label}" /></td>
          {/each}
        </tr>
      {/each}
    </tbody>
  </table>
{/snippet}

<div class="panel">
  {@render segmented("Compare", MODES, compare.mode, (id) => compare.setMode(id as Kind))}
  <h2>View</h2>
  {@render segmented("View", VIEWS, compare.view, (id) => compare.setView(id as View), true)}
  <p class="hint">{compare.viewInfo.hint} Press 1 to 3 to switch views.</p>
  {#if compare.view === "single"}
    <h2>Source</h2>
    {@render matrix([{ id: "src", color: compare.singleLayer.color, current: compare.single[compare.mode], pick: (id) => (compare.single[compare.mode] = id) }])}
    <p class="hint">Press [ or ] to step through sources.</p>
  {:else}
    <h2>Compare</h2>
    {@render matrix((["a", "b"] as const).map((slot) => ({ id: slot, color: SLOT_COLORS[slot], current: compare.pair[slot], pick: (id: string) => (compare.pairs[compare.mode][slot] = id) })))}
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
  .matrix tbody tr:hover {
    background: var(--cd-grey--300);
  }
</style>
