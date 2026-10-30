<script lang="ts">
  import {
    BASELINE,
    DEFAULT_FILTER,
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

  const ALL_SOURCES = Object.keys(SOURCES);

  const LEGEND: { kind: DiffType; label: string; swatch?: string }[] = [
    { kind: "differs", label: "Differs", swatch: "var(--cd-orange--300)" },
    { kind: "missing", label: "Missing", swatch: "var(--cd-grey--300)" },
    { kind: "several", label: "Several features" },
    { kind: "only", label: "One source only" },
  ];

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

  const dirty = $derived(JSON.stringify(filter) !== JSON.stringify(DEFAULT_FILTER));

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

{#snippet chips(label: string, options: { id: string; label: string; title?: string }[], current: string, pick: (id: string) => void)}
  <div class="chips" role="radiogroup" aria-label={label}>
    {#each options as o (o.id)}
      <button type="button" role="radio" aria-checked={current === o.id} class:active={current === o.id} title={o.title} onclick={() => pick(o.id)}>{o.label}</button>
    {/each}
  </div>
{/snippet}

{#snippet search()}
  <input type="search" placeholder="Search code or name" bind:value={filter.query} />
{/snippet}

{#snippet show()}
  {@render chips("Show", [{ id: "any", label: "Differences" }, { id: "all", label: "All" }], filter.diff === "all" ? "all" : "any", (id) => (filter.diff = id as DiffType))}
{/snippet}

{#snippet attributes()}
  {@render chips("Attribute", [{ id: "", label: "All" }, ...GROUPS.map((g) => ({ id: g.key, label: g.label }))], filter.group, (id) => (filter.group = id))}
{/snippet}

{#snippet sourceHead(source: string)}
  <th class:picked={filter.pair === source || (filter.pair && source === BASELINE)}>{SOURCES[source]}</th>
{/snippet}

{#snippet fixedCell(row: AttributeRow, group: (typeof GROUPS)[number], source: string)}
  {#if group.sources.includes(source)}
    {@const c = cellClass(row, group, source)}
    <td class:empty={c.empty} class:diff={c.diff} class:dim={c.dim}>{value(row, group.key, source)}</td>
  {:else}
    <td class="na"></td>
  {/if}
{/snippet}

{#snippet legend()}
  <div class="legend" role="group" aria-label="Difference type">
    {#each LEGEND as l (l.kind)}
      <button type="button" aria-pressed={filter.diff === l.kind} class:active={filter.diff === l.kind} onclick={() => (filter.diff = filter.diff === l.kind ? "any" : l.kind)}>
        {#if l.swatch}<span class="swatch" style:background={l.swatch}></span>{/if}{l.label}
      </button>
    {/each}
  </div>
{/snippet}

{#snippet facetSelects()}
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
{/snippet}

{#snippet reset()}
  {#if dirty}<button type="button" class="btn" onclick={() => (filter = { ...DEFAULT_FILTER })}>Reset</button>{/if}
{/snippet}

{#snippet total()}
  <span class="count">{shown.length} of {rows.length} codes</span>
{/snippet}

<div class="table-view">
  <aside class="sidebar">
    {@render search()}
    <h2>Show</h2>
    {@render show()}
    {@render total()}
    <h2>Difference</h2>
    {@render legend()}
    <h2>Attribute</h2>
    {@render attributes()}
    <h2>Compare with {SOURCES[BASELINE]}</h2>
    {@render chips("Compare", [{ id: "", label: "All sources" }, ...pairs.map((p) => ({ id: p, label: SOURCES[p] }))], filter.pair, (id) => (filter.pair = id))}
    <h2>Filter</h2>
    <div class="facets">{@render facetSelects()}</div>
    {@render reset()}
  </aside>
  {#if failed}
    <p>Could not load attributes.json.</p>
  {:else}
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th class="code">ISO3</th>
            <th class="attr">Attribute</th>
            {#each ALL_SOURCES as source (source)}{@render sourceHead(source)}{/each}
          </tr>
        </thead>
        <tbody>
          {#each shown as row (row.iso3)}
            {#each groups as group, gi (group.key)}
              <tr class:start={gi === 0}>
                {#if gi === 0}<th class="code" rowspan={groups.length}>{row.iso3}</th>{/if}
                <td class="attr">{group.label}</td>
                {#each ALL_SOURCES as source (source)}{@render fixedCell(row, group, source)}{/each}
              </tr>
            {/each}
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<style>
  .table-view {
    display: grid;
    grid-template-columns: 17rem 1fr;
    height: 100%;
    min-height: 0;
    font-size: 0.8125rem;
  }
  .count {
    color: var(--brand-grey--text);
  }
  .chips,
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
  }
  .chips button,
  .legend button {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.25rem 0.6rem;
    border: 1px solid var(--cd-grey--500);
    border-radius: 999px;
    background: var(--cd-white);
    color: var(--cd-grey--800);
    font-size: 0.75rem;
    cursor: pointer;
  }
  .chips button:hover:not(.active),
  .legend button:hover:not(.active) {
    background: var(--cd-grey--300);
  }
  .chips button.active,
  .legend button.active {
    background: var(--brand-primary--text);
    border-color: var(--brand-primary--text);
    color: var(--cd-white);
  }
  .swatch {
    width: 0.7rem;
    height: 0.7rem;
    border: 1px solid var(--cd-grey--500);
    border-radius: 2px;
  }
  thead th.picked {
    color: var(--brand-primary--text);
    font-weight: 600;
  }
  tr.start > * {
    border-top: 1px solid var(--cd-grey--400);
  }
  th.code {
    vertical-align: top;
  }
  .attr {
    min-width: 6rem;
    color: var(--brand-grey--text);
  }
  .na {
    background: repeating-linear-gradient(45deg, transparent 0 4px, var(--cd-grey--300) 4px 6px);
  }
  .sidebar {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    padding: 0.75rem 1rem;
    border-right: 1px solid var(--cd-grey--400);
    overflow: auto;
  }
  .sidebar h2 {
    margin: 0.75rem 0 0;
    font-size: 0.6875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--cd-grey--700);
  }
  .facets {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .facets label {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    color: var(--cd-grey--700);
    font-size: 0.6875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .sidebar .btn {
    align-self: start;
    margin-top: 0.5rem;
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
    top: 0;
    border-bottom: 1px solid var(--cd-grey--400);
    background: var(--cd-white);
    font-weight: 600;
    z-index: 1;
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
