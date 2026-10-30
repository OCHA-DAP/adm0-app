<script lang="ts">
  import type { CompareState } from "$lib/compare.svelte";
  import Swatch from "$lib/components/Swatch.svelte";

  let { compare }: { compare: CompareState } = $props();
</script>

{#if compare.hits.length}
  <div class="panel">
    <header>
      <h2>At this point</h2>
      <button aria-label="Close" onclick={() => (compare.hits = [])}>×</button>
    </header>
    {#each compare.hits as hit, i (i)}
      <section>
        <h3>
          {#if hit.slot}<span class="badge" style:--color={hit.color}>{hit.slot.toUpperCase()}</span>{/if}
          <Swatch kind={compare.mode} color={hit.color} />{hit.label}
        </h3>
        <table>
          <tbody>
            {#each Object.entries(hit.properties) as [key, value] (key)}
              <tr><th>{key}</th><td>{value}</td></tr>
            {/each}
          </tbody>
        </table>
      </section>
    {/each}
  </div>
{/if}

<style>
  .panel {
    right: 0.75rem;
    width: 22rem;
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  h2 {
    margin: 0;
  }
  button {
    border: 0;
    background: none;
    font-size: 1.25rem;
    line-height: 1;
    cursor: pointer;
    color: var(--brand-grey--text);
  }
  section + section {
    border-top: 1px solid var(--cd-grey--400);
  }
  h3 {
    display: flex;
    align-items: center;
    font-family: var(--brand-font);
    font-size: 0.8125rem;
    font-weight: 600;
    color: var(--cd-grey--900);
    margin: 0.75rem 0 0.3rem;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.75rem;
    line-height: 1.4;
    margin-bottom: 0.6rem;
  }
  th,
  td {
    padding: 0.1rem 0.75rem 0.1rem 0;
    border: 0;
    word-break: break-word;
  }
  th {
    color: var(--cd-grey--800);
    font-weight: 400;
    width: 40%;
  }
  td {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
</style>
