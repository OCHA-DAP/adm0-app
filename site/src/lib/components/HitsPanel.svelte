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
  h3 {
    font-size: 0.875rem;
    margin: 0.75rem 0 0.25rem;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.75rem;
  }
  th,
  td {
    padding: 0.15rem 0.3rem;
    word-break: break-word;
  }
  th {
    color: var(--brand-grey--text);
    font-weight: 400;
    width: 40%;
  }
</style>
