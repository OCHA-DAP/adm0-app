<script lang="ts">
  import {
    BASELINE,
    DEFAULT_FILTER,
    DIFF_TYPES,
    FACETS,
    GROUPS,
    SOURCES,
    compares,
    facetValue,
    groupsInScope,
    majority,
    matches,
    sourcesFor,
    TIE,
    value,
    type AttributeRow,
    type DiffType,
    type Facet,
    type Filter,
  } from "$lib/attributes";

  let { tilesBase }: { tilesBase: string } = $props();

  let rows = $state.raw<AttributeRow[]>([]);
  let failed = $state(false);
  let filter = $state<Filter>({ ...DEFAULT_FILTER });

  $effect(() => {
    fetch(`${tilesBase}/attributes.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data: AttributeRow[]) => (rows = data))
      .catch(() => (failed = true));
  });

  const shown = $derived(rows.filter((row) => matches(row, filter)));
  const groups = $derived(groupsInScope(filter));
  const pairs = Object.keys(SOURCES).filter((s) => s !== BASELINE);
  const facets = Object.keys(FACETS) as Facet[];

  // Rows each option would keep, with every other filter left as it is.
  function count<K extends keyof Filter>(key: K, option: Filter[K]) {
    const trial = { ...filter, [key]: option };
    return rows.filter((row) => matches(row, trial)).length;
  }

  const facetOptions = $derived(
    Object.fromEntries(
      facets.map((f) => [f, [...new Set(rows.map((r) => facetValue(r, f)))].sort()]),
    ) as Record<Facet, string[]>,
  );

  function cellClass(row: AttributeRow, group: (typeof GROUPS)[number], source: string) {
    const v = value(row, group.key, source);
    const sources = sourcesFor(group, filter);
    const inPair = sources.includes(source);
    let diff = false;
    if (v && inPair && compares(group, filter)) {
      const top = majority(row, group, sources);
      diff = top !== null && (!!filter.pair || top === TIE || v !== top);
    }
    return { empty: !v, diff, dim: !inPair };
  }
</script>

<div class="table-view">
  <div class="controls">
    <input type="search" placeholder="Search code or name" bind:value={filter.query} />
    <label>
      Attribute
      <select bind:value={filter.group}>
        <option value="">All ({count("group", "")})</option>
        {#each GROUPS as g (g.key)}<option value={g.key}>{g.label} ({count("group", g.key)})</option>{/each}
      </select>
    </label>
    <label>
      Differences
      <select bind:value={filter.diff}>
        {#each Object.entries(DIFF_TYPES) as [key, label] (key)}
          <option value={key}>{label} ({count("diff", key as DiffType)})</option>
        {/each}
      </select>
    </label>
    <label>
      Compare
      <select bind:value={filter.pair}>
        <option value="">All sources ({count("pair", "")})</option>
        {#each pairs as p (p)}<option value={p}>{SOURCES[BASELINE]} vs {SOURCES[p]} ({count("pair", p)})</option>{/each}
      </select>
    </label>
    {#each facets as f (f)}
      <label>
        {FACETS[f].label}
        <select bind:value={filter[f]}>
          <option value="">Any</option>
          {#each facetOptions[f] as option (option)}
            {@const n = count(f, option)}
            {#if n > 0 || filter[f] === option}<option value={option}>{option} ({n})</option>{/if}
          {/each}
        </select>
      </label>
    {/each}
    <button type="button" class="btn" onclick={() => (filter = { ...DEFAULT_FILTER })}>Reset</button>
    <span class="count">{shown.length} of {rows.length} codes</span>
  </div>
  {#if failed}
    <p>Could not load attributes.json.</p>
  {:else}
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th rowspan="2" class="code">ISO3</th>
            {#each groups as group (group.key)}
              <th colspan={group.sources.length} class="first">{group.label}</th>
            {/each}
          </tr>
          <tr>
            {#each groups as group (group.key)}
              {#each group.sources as source, i (source)}
                <th class:first={i === 0}>{SOURCES[source]}</th>
              {/each}
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each shown as row (row.iso3)}
            <tr>
              <th class="code">{row.iso3}</th>
              {#each groups as group (group.key)}
                {#each group.sources as source, i (source)}
                  {@const c = cellClass(row, group, source)}
                  <td class:first={i === 0} class:empty={c.empty} class:diff={c.diff} class:dim={c.dim}>
                    {value(row, group.key, source)}
                  </td>
                {/each}
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<style>
  .table-view {
    display: flex;
    flex-direction: column;
    height: 100%;
    font-size: 0.8125rem;
  }
  .controls {
    display: flex;
    flex-wrap: wrap;
    align-items: end;
    gap: 0.5rem 1rem;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--cd-grey--400);
  }
  .controls label {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    color: var(--cd-grey--700);
    font-size: 0.6875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .controls select,
  .controls input {
    max-width: 14rem;
  }
  .controls input[type="search"] {
    width: 14rem;
  }
  .count {
    color: var(--brand-grey--text);
    margin-left: auto;
  }
  .scroll {
    flex: 1;
    overflow: auto;
  }
  table {
    border-collapse: separate;
    border-spacing: 0;
  }
  th,
  td {
    padding: 0.25rem 0.5rem;
    min-width: 8rem;
    max-width: 16rem;
  }
  thead th {
    position: sticky;
    background: var(--cd-white);
    font-weight: 600;
    z-index: 1;
  }
  thead tr:first-child th {
    top: 0;
  }
  thead tr:nth-child(2) th {
    top: 1.6rem;
    color: var(--brand-grey--text);
    font-weight: 400;
  }
  .first {
    border-left: 2px solid var(--cd-grey--400);
  }
  .code {
    position: sticky;
    left: 0;
    background: var(--cd-white);
    min-width: 4rem;
    z-index: 2;
  }
  .empty {
    background: var(--cd-grey--300);
  }
  .diff {
    background: var(--cd-orange--300);
  }
  .dim {
    opacity: 0.35;
  }
</style>
