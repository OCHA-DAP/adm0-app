<script lang="ts">
  import { SLOT_COLORS, type Focus } from "$lib/compare.svelte";
  import {
    ATTRIBUTE_SOURCE,
    DEFAULT_FILTER,
    GROUPS,
    SOURCES,
    compares,
    groupsInScope,
    majority,
    matches,
    sourcesFor,
    TIE,
    value,
    type AttributeRow,
    type Part,
    type DiffType,
    type Filter,
  } from "$lib/attributes";

  let {
    rows,
    failed,
    focus,
    drawn,
    pair,
    split = false,
    onfocus,
  }: {
    rows: AttributeRow[];
    failed: boolean;
    focus: Focus | null;
    drawn: string[];
    pair: { a: string; b: string };
    split?: boolean;
    onfocus: (row: AttributeRow, part?: Part | null) => void;
  } = $props();

  // The swatches double as the legend for the cell colors.
  const SHOW: { id: DiffType; label: string; swatch?: string }[] = [
    { id: "all", label: "All" },
    { id: "differs", label: "Differs", swatch: "var(--cd-orange--300)" },
    { id: "missing", label: "Missing", swatch: "var(--cd-grey--300)" },
  ];

  let filter = $state<Filter>({ ...DEFAULT_FILTER });
  // With the map pair in charge, the table shows and compares only A and B.
  const ab = $derived([ATTRIBUTE_SOURCE[pair.a], ATTRIBUTE_SOURCE[pair.b]]);
  // Split shows only the map's A and B; the full table shows the sources toggled on.
  const ALL = Object.keys(SOURCES);
  const scope = $derived(split ? { ...filter, sources: ab } : filter);
  const on = $derived(filter.sources.length ? filter.sources : ALL);
  const columns = $derived(split ? ab : on);

  // At least two sources stay on; all on is stored as empty.
  function toggle(source: string) {
    const next = on.includes(source) ? on.filter((s) => s !== source) : ALL.filter((s) => s === source || on.includes(s));
    if (next.length < 2) return;
    filter.sources = next.length === ALL.length ? [] : next;
  }
  // In Split the active Attribute chip already names a single attribute.
  const labelled = $derived(!split || !filter.group);
  let body = $state<HTMLElement>();

  // The focused code stays listed even when the filters would hide it.
  const shown = $derived(rows.filter((row) => row.iso3 === focus?.iso3 || matches(row, scope)));

  // Scrolls once per code, so picking its parts leaves the table still.
  const focusedCode = $derived(focus?.iso3);
  $effect(() => {
    const iso3 = focusedCode;
    if (iso3) requestAnimationFrame(() => body?.querySelector(`[data-iso3="${iso3}"]`)?.scrollIntoView({ block: "start" }));
  });
  const groups = $derived(groupsInScope(filter));

  const dirty = $derived(JSON.stringify(filter) !== JSON.stringify(DEFAULT_FILTER));

  function cellClass(row: AttributeRow, group: (typeof GROUPS)[number], source: string) {
    const v = value(row, group.key, source);
    const sources = sourcesFor(group, scope);
    const inPair = sources.includes(source);
    let diff = false;
    if (v && inPair && compares(group, scope)) {
      const top = majority(row, group, sources);
      diff = top !== null && (scope.sources.length === 2 || top === TIE || v !== top);
    }
    return { empty: !v, diff, dim: !inPair };
  }
</script>

{#snippet segmented(label: string, options: { id: string; label: string; title?: string; swatch?: string }[], current: string, pick: (id: string) => void)}
  <div class="segmented" role="radiogroup" aria-label={label}>
    {#each options as o (o.id)}
      <button type="button" role="radio" aria-checked={current === o.id} class:active={current === o.id} title={o.title} onclick={() => pick(o.id)}>{#if o.swatch}<span class="swatch" style:background={o.swatch}></span>{/if}{o.label}</button>
    {/each}
  </div>
{/snippet}

{#snippet search()}
  <input type="search" placeholder="Search code or name" bind:value={filter.query} />
{/snippet}

{#snippet show()}
  {@render segmented("Show", SHOW, filter.diff, (id) => (filter.diff = id as DiffType))}
{/snippet}

{#snippet attributes()}
  {@render segmented("Attribute", [{ id: "", label: "All" }, ...GROUPS.map((g) => ({ id: g.key, label: g.label }))], filter.group, (id) => (filter.group = id))}
{/snippet}

{#snippet sourceHead(source: string)}
  {@const slot = !split ? null : source === ab[0] ? "a" : "b"}
  <th>
    {#if slot}<span class="badge" style:--color={SLOT_COLORS[slot]}>{slot.toUpperCase()}</span>{/if}{SOURCES[source]}
  </th>
{/snippet}

{#snippet fixedCell(row: AttributeRow, group: (typeof GROUPS)[number], source: string)}
  {#if group.key === "count" && group.sources.includes(source)}
    {@render partChips(row, source)}
  {:else if group.sources.includes(source)}
    {@const c = cellClass(row, group, source)}
    <td class:empty={c.empty} class:diff={c.diff} class:dim={c.dim}>{value(row, group.key, source)}</td>
  {:else}
    <td class="na"></td>
  {/if}
{/snippet}

{#snippet partChips(row: AttributeRow, source: string)}
  {@const parts = (row.parts as Part[] | null) ?? []}
  {@const mine = parts.filter((p) => p.s === source)}
  {@const picked = row.iso3 === focus?.iso3 ? focus.part : null}
  {#if mine.length}
    <td><div class="parts">
      {#each mine as part (part.id)}
        {@const label = part.label ?? "(no name)"}
        {#if drawn.includes(part.layer)}
          <!-- Picking the active part again goes back to the whole code. -->
          <button
            type="button"
            title={label}
            class:active={picked?.id === part.id}
            class:unnamed={!part.label}
            onclick={() => onfocus(row, picked?.id === part.id ? null : part)}>{label}</button
          >
        {:else}
          <span class:unnamed={!part.label} title="{label}: pick this source as A or B to see it on the map">{label}</span>
        {/if}
      {/each}
    </div></td>
  {:else}
    <td class="na"></td>
  {/if}
{/snippet}

{#snippet reset()}
  {#if dirty}<button type="button" class="btn" onclick={() => (filter = { ...DEFAULT_FILTER })}>Reset</button>{/if}
{/snippet}

{#snippet total()}
  <span class="count">{shown.length} of {rows.length} codes</span>
{/snippet}

<div class="table-view">
  <aside class="sidebar">
    <section>{@render search()}</section>
    {#if !split}
      <section>
        <h2>Sources</h2>
        <div class="toggles" role="group" aria-label="Sources">
          {#each ALL as s (s)}
            <button type="button" aria-pressed={on.includes(s)} class:on={on.includes(s)} disabled={on.includes(s) && on.length === 2} onclick={() => toggle(s)}>{on.includes(s) ? "✓ " : ""}{SOURCES[s]}</button>
          {/each}
        </div>
      </section>
    {/if}
    <section>
      <h2>Show</h2>
      {@render show()}
      {@render total()}
    </section>
    <section>
      <h2>Attribute</h2>
      {@render attributes()}
    </section>
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
            {#if labelled}<th class="attr">Attribute</th>{/if}
            {#each columns as source (source)}{@render sourceHead(source)}{/each}
          </tr>
        </thead>
        <tbody bind:this={body}>
          {#each shown as row (row.iso3)}
            {@const focused = row.iso3 === focus?.iso3}
            {#each groups as group, gi (group.key)}
              <tr class:start={gi === 0} class:focused data-iso3={gi === 0 ? row.iso3 : undefined}>
                {#if gi === 0}<th class="code" rowspan={groups.length}><button type="button" class="code-link" title="Show on map" onclick={() => onfocus(row)}>{row.iso3}</button></th>{/if}
                {#if labelled}<td class="attr">{group.label}</td>{/if}
                {#each columns as source (source)}{@render fixedCell(row, group, source)}{/each}
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
    grid-template-rows: auto 1fr;
    height: 100%;
    min-height: 0;
    font-size: 0.8125rem;
  }
  .count {
    color: var(--brand-grey--text);
  }
  /* Multi-select toggles are outlined pills so they read differently from the segmented single choices. */
  .toggles {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
  }
  .toggles button {
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
  .toggles button:hover:not(.on) {
    background: var(--cd-grey--300);
  }
  .toggles button.on {
    border-color: var(--brand-primary--text);
    background: var(--cd-blue--lightest);
    color: var(--brand-primary--text);
  }
  .segmented {
    display: flex;
    border: 1px solid var(--cd-grey--500);
    border-radius: var(--brand-radius--sm);
    overflow: hidden;
    background: var(--cd-white);
  }
  .segmented button {
    padding: 0.25rem 0.6rem;
    border: none;
    border-left: 1px solid var(--cd-grey--400);
    background: var(--cd-white);
    color: var(--cd-grey--800);
    font-size: 0.75rem;
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
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
  .swatch {
    width: 0.7rem;
    height: 0.7rem;
    border: 1px solid var(--cd-grey--500);
    border-radius: 2px;
  }
  tr[data-iso3] {
    scroll-margin-top: 2rem;
  }
  thead th.code {
    z-index: 3;
  }
  tr.start > * {
    border-top: 1px solid var(--cd-grey--400);
  }
  th.code {
    vertical-align: top;
  }
  .code-link {
    padding: 0;
    border: 0;
    background: none;
    color: var(--brand-primary--text);
    font: inherit;
    font-weight: 600;
    text-decoration: underline;
    text-decoration-color: var(--cd-grey--400);
    text-underline-offset: 2px;
    cursor: pointer;
  }
  .code-link:hover {
    text-decoration-color: currentColor;
  }
  tr.focused > th,
  tr.focused > .attr {
    background-color: var(--cd-blue--lightest);
  }
  .parts {
    display: flex;
    flex-direction: column;
    align-items: start;
    gap: 0.2rem;
  }
  .parts button,
  .parts span {
    max-width: 12rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    padding: 0.1rem 0.45rem;
    border: 1px solid var(--cd-grey--500);
    border-radius: 999px;
    background: var(--cd-white);
    font: inherit;
    font-size: 0.75rem;
    text-align: left;
  }
  .parts button {
    color: var(--brand-primary--text);
    cursor: pointer;
  }
  .parts button:hover:not(.active) {
    background: var(--cd-grey--300);
  }
  .parts button.active {
    background: var(--brand-primary--text);
    border-color: var(--brand-primary--text);
    color: var(--cd-white);
  }
  .parts span {
    border-style: dashed;
    color: var(--brand-grey--text);
  }
  .parts .unnamed:not(.active) {
    color: var(--brand-grey--text);
    font-style: italic;
  }
  .attr {
    min-width: 6rem;
    color: var(--brand-grey--text);
  }
  .na {
    background: repeating-linear-gradient(45deg, transparent 0 4px, var(--cd-grey--300) 4px 6px);
  }
  /* Controls wrap in a strip above the table, taking its width rather than setting it. */
  .sidebar {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1.5rem;
    max-height: 40vh;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--cd-grey--400);
    overflow: auto;
    contain: inline-size;
  }
  .sidebar section {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem;
  }
  .sidebar h2 {
    margin: 0;
    font-size: 0.6875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--cd-grey--700);
  }
  .sidebar .btn {
    align-self: center;
  }
  .scroll {
    flex: 1;
    overflow: auto;
  }
  table {
    width: 100%;
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
