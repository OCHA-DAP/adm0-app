<script lang="ts">
  import { SLOT_COLORS, type Focus, type ItemFocus } from "$lib/compare.svelte";
  import Segmented from "$lib/components/Segmented.svelte";
  import {
    DEFAULT_FILTER,
    ENTITY,
    SOURCES,
    attributeGroups,
    groupsInScope,
    itemTitle,
    marked,
    matches,
    sourcesFor,
    value,
    type AttributeGroup,
    type AttributeRow,
    type DiffType,
    type Filter,
    type ItemRow,
    type Part,
  } from "$lib/attributes";

  let {
    rows,
    items,
    failed,
    focus,
    item,
    drawn,
    pair,
    split = false,
    onfocus,
    onitem,
  }: {
    rows: AttributeRow[];
    items: ItemRow[];
    failed: boolean;
    focus: Focus | null;
    item: ItemFocus | null;
    drawn: string[];
    pair: { a: string; b: string };
    split?: boolean;
    onfocus: (row: AttributeRow, part?: Part | null) => void;
    onitem: (row: ItemRow, label: string) => void;
  } = $props();

  // The swatches double as the legend for the cell colors.
  const SHOW: { id: DiffType; label: string; swatch?: string }[] = [
    { id: "all", label: "All" },
    { id: "differs", label: "Differs", swatch: "var(--cd-orange--300)" },
  ];

  let filter = $state<Filter>({ ...DEFAULT_FILTER });
  // Split lists what the map can show; the full table lists attributes unrelated to geometry.
  let list = $state<"differences" | "features">("differences");
  const view = $derived(split ? list : "attributes");
  const geometry = $derived(view === "differences");

  // With the map pair in charge, the table shows and compares only A and B, against A.
  const ab = $derived([pair.a, pair.b]);
  const diffPair = $derived([...ab].sort().join("|"));
  const ALL = $derived(geometry ? ENTITY.sources : Object.keys(SOURCES));
  const scope = $derived(split ? { ...filter, sources: ab, ref: pair.a } : filter);
  const on = $derived(filter.sources.length ? ALL.filter((s) => filter.sources.includes(s)) : ALL);
  const columns = $derived.by(() => {
    const cols = split ? ab : on;
    return scope.ref && cols.includes(scope.ref) ? [scope.ref, ...cols.filter((s) => s !== scope.ref)] : cols;
  });

  // At least two sources stay on; all on is stored as empty.
  function toggle(source: string) {
    const next = on.includes(source) ? on.filter((s) => s !== source) : ALL.filter((s) => s === source || on.includes(s));
    if (next.length < 2) return;
    filter.sources = next.length === Object.keys(SOURCES).length ? [] : next;
  }
  let body = $state<HTMLElement>();

  const allGroups = $derived(attributeGroups(rows[0]));
  const attrGroups = $derived(allGroups.filter((g) => (g.key === "count") === (view === "features")));
  const rowScope = $derived(view === "features" ? { ...scope, group: "count" } : scope);
  const groups = $derived(groupsInScope(attrGroups, rowScope));
  const labelled = $derived(view === "attributes" && !filter.group);

  // Items with patches in the map's pair, plus those with no OSM land to patch.
  const itemScope = $derived({ ...scope, group: ENTITY.key });
  function itemShown(it: ItemRow) {
    if (it.type !== "no_land" && !(it.pairs ?? []).includes(diffPair)) return false;
    return matches(it, [ENTITY], itemScope);
  }
  const shownItems = $derived(items.filter((it) => it.item === item?.ids[0] || itemShown(it)));

  const shown = $derived(rows.filter((row) => row.iso3 === focus?.iso3 || matches(row, attrGroups, rowScope)));

  // Scrolls once per code or item, only when the row sits outside the area below the sticky header.
  // scrollIntoView would also scroll the hidden pane's ancestors and slide the table over the map-only view.
  let scroller = $state<HTMLElement>();
  function scrollTo(selector: string) {
    requestAnimationFrame(() => {
      const row = body?.querySelector<HTMLElement>(selector);
      if (!row || !scroller) return;
      const head = scroller.querySelector("thead")?.getBoundingClientRect().height ?? 0;
      const box = row.getBoundingClientRect();
      const top = box.top - scroller.getBoundingClientRect().top - head;
      if (top < 0 || top + box.height > scroller.clientHeight - head) scroller.scrollTop += top;
    });
  }
  const focusedCode = $derived(focus?.iso3);
  $effect(() => {
    if (focusedCode) scrollTo(`[data-iso3="${focusedCode}"]`);
  });
  const focusedItem = $derived(item?.ids[0]);
  $effect(() => {
    if (!focusedItem) return;
    list = "differences";
    scrollTo(`[data-item="${focusedItem}"]`);
  });

  const visible = $derived(geometry ? columns : columns.filter((s) => groups.some((g) => g.sources.includes(s))));
  const dirty = $derived(JSON.stringify(filter) !== JSON.stringify(DEFAULT_FILTER));
  function reset() {
    filter = { ...DEFAULT_FILTER };
  }

  function cellClass(row: AttributeRow | ItemRow, group: AttributeGroup, source: string) {
    const v = value(row as AttributeRow, group.key, source);
    const sources = sourcesFor(group, scope);
    const inPair = sources.includes(source);
    const diff = !!v && inPair && marked(row, group, sources, scope.ref).has(source);
    return { empty: !v, diff, dim: !inPair, ref: source === scope.ref };
  }
  const count = $derived(
    geometry ? `${shownItems.length} differences` : `${shown.length} of ${rows.length} codes`,
  );
  const slotOf = (source: string) => (source === ab[0] ? "a" : "b");
  // Differences grouped like Features: under A's code, or B's when A has none, codes in order.
  const groupCode = (it: ItemRow) => ab.map((s) => String(it[`code_${s}`] ?? "")).find(Boolean) ?? "";
  const itemGroups = $derived.by(() => {
    const groups = new Map<string, ItemRow[]>();
    for (const it of shownItems) groups.set(groupCode(it), [...(groups.get(groupCode(it)) ?? []), it]);
    return [...groups].sort(([x], [y]) => x.localeCompare(y, "en", { sensitivity: "base" }));
  });
</script>

{#snippet fixedCell(row: AttributeRow, group: AttributeGroup, source: string)}
  {#if group.key === "count" && group.sources.includes(source)}
    {@render partChips(row, source)}
  {:else if group.sources.includes(source)}
    {@const c = cellClass(row, group, source)}
    <td class:empty={c.empty} class:diff={c.diff} class:dim={c.dim} class:ref={c.ref}>{value(row, group.key, source)}</td>
  {:else}
    <td class="na"></td>
  {/if}
{/snippet}

{#snippet entityCell(it: ItemRow, source: string)}
  {@const c = cellClass(it, ENTITY, source)}
  {#if !ENTITY.sources.includes(source)}<td class="na"></td>{:else}
  {@const [code, name] = [String(it[`code_${source}`] ?? ""), it[`name_${source}`]]}
  <td class:empty={!name} class:dim={c.dim} class:ref={c.ref} class:absent={it.missing?.includes(source)} title={it.missing?.includes(source) ? "No entity of its own here" : undefined}
    >{#if code && code !== groupCode(it)}<span class="iso" style:color={SLOT_COLORS[slotOf(source)]}>{code}</span>{/if}{name ?? ""}{#if c.ref && it.type === "no_land"}<div class="meta">No OSM land</div>{/if}</td
  >{/if}
{/snippet}

{#snippet partChips(row: AttributeRow, source: string)}
  {@const mine = (row.parts ?? []).filter((p) => p.s === source)}
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

{#snippet sourceHead(source: string)}
  {@const slot = !split ? null : source === ab[0] ? "a" : "b"}
  <th class:ref={source === scope.ref}>{#if slot}<span class="badge" style:--color={SLOT_COLORS[slot]}>{slot.toUpperCase()}</span>{/if}{SOURCES[source]}</th>
{/snippet}

<div class="table-view">
  <aside class="sidebar">
    {#if split}
      <section>
        <Segmented label="List" options={[{ id: "differences", label: "Differences" }, { id: "features", label: "Features" }]} current={list} pick={(id) => (list = id as typeof list)} />
      </section>
    {/if}
    <section><input type="search" placeholder="Search code or name" bind:value={filter.query} /></section>
    <section>
      <h2>Show</h2>
      <Segmented label="Show" options={SHOW} current={filter.diff} pick={(id) => (filter.diff = id as DiffType)} />
      <span class="count">{count}</span>
    </section>
    {#if view === "attributes"}
      <section>
        <h2>Attribute</h2>
        <Segmented label="Attribute" options={[{ id: "", label: "All" }, ...attrGroups.map((g) => ({ id: g.key, label: g.label }))]} current={filter.group} pick={(id) => (filter.group = id)} />
      </section>
    {/if}
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
    {#if dirty}<button type="button" class="btn" onclick={reset}>Reset</button>{/if}
  </aside>
  {#if failed}
    <p>Could not load attributes.json.</p>
  {:else}
    <div class="scroll" bind:this={scroller}>
      <table>
        <thead>
          <tr>
            <th class="code">ISO3</th>
            {#if labelled && !geometry}<th class="attr">Attribute</th>{/if}
            {#each visible as source (source)}{@render sourceHead(source)}{/each}
          </tr>
        </thead>
        <tbody bind:this={body}>
          {#if geometry}
            {#each itemGroups as [code, group] (code)}
              {#each group as it, i (it.item)}
                <tr class="clickable" class:start={i === 0} class:focused={it.item === item?.ids[0]} data-item={it.item} tabindex="0" role="button"
                  onclick={() => onitem(it, itemTitle(it))} onkeydown={(e) => e.key === "Enter" && onitem(it, itemTitle(it))}>
                  {#if i === 0}<th class="code group" rowspan={group.length}>{code}</th>{/if}
                  {#each visible as source (source)}{@render entityCell(it, source)}{/each}
                </tr>
              {/each}
            {/each}
          {:else}
            {#each shown as row (row.iso3)}
              {@const focused = row.iso3 === focus?.iso3}
              {#each groups as group, gi (group.key)}
                <tr class:start={gi === 0} class:focused data-iso3={gi === 0 ? row.iso3 : undefined}>
                  {#if gi === 0}<th class="code" rowspan={groups.length}><button type="button" class="code-link" title="Show on map" onclick={() => { if (!split) list = "features"; onfocus(row); }}>{row.iso3}</button></th>{/if}
                  {#if labelled}<td class="attr">{group.label}</td>{/if}
                  {#each visible as source (source)}{@render fixedCell(row, group, source)}{/each}
                </tr>
              {/each}
            {/each}
          {/if}
        </tbody>
      </table>
      {#if (geometry ? !shownItems.length : rows.length && !shown.length)}
        <p class="none">Nothing matches.</p>
      {/if}
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
  .none {
    padding: 1rem;
    color: var(--brand-grey--text);
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
  th .code-link {
    text-align: left;
  }
  .meta {
    color: var(--brand-grey--text);
    font-size: 0.7rem;
    font-weight: 400;
  }
  th.ref {
    text-decoration: underline;
    text-underline-offset: 3px;
  }
  tr.clickable {
    cursor: pointer;
  }
  tr.clickable.focused > td {
    background-color: var(--cd-blue--lightest);
  }
  th.group {
    font-weight: 600;
    cursor: default;
  }
  .iso {
    margin-right: 0.35em;
    font-size: 0.75rem;
    font-weight: 600;
  }
  .absent {
    outline: 1px dashed var(--cd-grey--600);
    outline-offset: -3px;
  }
</style>
