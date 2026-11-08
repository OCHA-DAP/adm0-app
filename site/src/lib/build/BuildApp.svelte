<script lang="ts">
  import HitsPanel from "$lib/components/HitsPanel.svelte";
  import PageSwitch from "$lib/components/PageSwitch.svelte";
  import PasswordGate from "$lib/components/PasswordGate.svelte";
  import Segmented from "$lib/components/Segmented.svelte";
  import { BASEMAPS, CompareState, SLOT_COLORS, type Basemap, type Hit } from "$lib/compare.svelte";
  import BuildMap from "$lib/build/BuildMap.svelte";

  interface Change {
    id: string;
    type: string;
    title: string;
    km2: number | null;
    units: number;
    bbox: number[] | null;
    values?: { un_objectid?: number; un: string; un_name: string; gaul: string; gaul_name: string; km2: number }[];
    largest_patch_bbox?: number[];
    review?: boolean;
  }
  interface Step {
    id: string;
    title: string;
    summary: string;
    types: string[];
    compare?: string[];
    legend?: string[];
    labels?: boolean;
  }
  const MIN_LINE_KM2 = 10;
  const km2 = new Intl.NumberFormat("en", { maximumFractionDigits: 1 });

  let tilesBase = $state<string | null>(null);
  let steps = $state.raw<Step[]>([]);
  let changes = $state.raw<Change[]>([]);
  let failed = $state(false);
  let stepIndex = $state(0);
  let change = $state.raw<Change | null>(null);
  let allLines = $state(false);
  let collapsed = $state(true);
  const compare = new CompareState();
  compare.mode = "polygon";

  const step = $derived(steps[stepIndex]);
  const border = $derived(change?.type === "line_update" ? change.id.slice(2).split("-") : null);
  const byArea = (a: Change, b: Change) => (b.km2 ?? 0) - (a.km2 ?? 0);
  const stepChanges = (s: Step) => {
    const list = changes.filter((c) => s.types.includes(c.type));
    return s.types.includes("un_error") ? list.sort(byArea) : list;
  };
  const unitChanges = $derived(step?.compare ? stepChanges(step).filter((c) => c.units > 0).map((c) => c.id) : []);
  const isSmallLine = (c: Change) => c.type === "line_update" && (c.km2 ?? 0) < MIN_LINE_KM2;
  const entity = (code: string, name: string) => ({ code, name: name === code ? "" : name });
  function sides(c: Change) {
    const values = c.values ?? [];
    const sources = [...new Map(values.map((v) => [v.un, entity(v.un, v.un_name)])).values()];
    if (!values.length) return { before: [], after: [] };
    return { before: sources, after: [entity(values[0].gaul, values[0].gaul_name)] };
  }
  const listedChanges = (s: Step) => stepChanges(s).filter((c) => allLines || !isSmallLine(c));

  $effect(() => {
    if (!tilesBase) return;
    const load = (name: string) => fetch(`/build/${name}.json`).then((r) => (r.ok ? r.json() : Promise.reject(r.status)));
    Promise.all([load("path"), load("changes")])
      .then(([p, c]) => {
        steps = p;
        changes = c;
      })
      .catch(() => (failed = true));
  });

  $effect(() => {
    compare.animate(!!step?.compare);
    return () => compare.animate(false);
  });

  function toggleLines() {
    allLines = !allLines;
    if (change && isSmallLine(change)) change = null;
  }

  function openStep(s: Step) {
    collapsed = s === step && !collapsed;
    if (s === step) return;
    stepIndex = steps.indexOf(s);
    change = null;
    compare.hits = [];
  }
</script>

{#snippet entities(list: { code: string; name: string }[])}
  {#each list as e (e.code)}
    <span class="entity">{#if e.code}<span class="code">{e.code}</span>{/if}{#if e.name}<span>{e.name}</span>{/if}</span>
  {/each}
{/snippet}

{#if !tilesBase}
  <PasswordGate onunlock={(base) => (tilesBase = base)} />
{:else}
  <div class="app">
    <header class="bar">
      <div class="heading"><span class="title">Rebuilding GAUL on UN Geodata 2023</span><PageSwitch current="build" /></div>
    </header>
    <div class="body">
      <aside>
        <p class="intro">The UN and GAUL exports both start from the lines and coastlines of UN Geodata 2023 (260 entities). The GAUL export keeps GAUL's 272 entities, which GAUL draws on the 2018 lines.</p>
        {#if failed}
          <p>The change list could not be loaded.</p>
        {/if}
        {#each steps as s (s.id)}
          <section class:current={s === step} class:open={s === step && !collapsed}>
            <button class="step" aria-expanded={s === step && !collapsed} onclick={() => openStep(s)}><span class="n">{steps.indexOf(s) + 1}</span>{s.title}</button>
            <div class="drawer">
              <div class="drawer-body" inert={s !== step || collapsed}>
                <p>{s.summary}</p>
                {#if listedChanges(s).length}
                  <ul>
                    {#each listedChanges(s) as c, i (c.id)}
                      {#if i === 0 && c.type !== "line_update"}
                        <li class="own-head"><span class="own"><span>UN Geodata</span><span>{c.type === "un_error" ? "Corrected" : "GAUL"}</span></span><span class="km2">Area</span></li>
                      {/if}
                      <li>
                        <button class:active={change === c} onclick={() => (change = c)}>
                          <span class="head">
                            {#if c.type === "line_update"}
                              {c.id.slice(2).replace("-", " | ")}
                            {:else}
                              {@const side = sides(c)}
                              <span class="own" title={c.values?.map((v) => `${v.un_name} → ${v.gaul_name}: ${km2.format(v.km2)} km²`).join("\n")}><span>{@render entities(side.before)}</span><span>{@render entities(side.after)}</span></span>
                            {/if}
                            {#if c.km2 != null}<span class="km2">{km2.format(c.km2)} km²</span>{/if}
                          </span>
                        </button>
                      </li>
                    {/each}
                  </ul>
                {/if}
                {#if stepChanges(s).some(isSmallLine)}
                  <button class="btn" onclick={toggleLines}>{allLines ? `Show only ${MIN_LINE_KM2} km² or more` : `Show all ${stepChanges(s).length}`}</button>
                {/if}
              </div>
            </div>
          </section>
        {/each}
      </aside>
      <div class="stage">
        <div class="panel">
          <h2>Basemap</h2>
          <Segmented stretch label="Basemap" options={BASEMAPS} current={compare.basemap} pick={(id) => (compare.basemap = id as Basemap)} />
          {#if step?.compare}
            <h2>Legend</h2>
            <ul class="legend">
              {#each [SLOT_COLORS.a, SLOT_COLORS.b] as color, i (i)}
                <li><span class="chip" style:background={color}></span>{step.legend?.[i] ?? ""}</li>
              {/each}
            </ul>
          {/if}
        </div>
        {#if changes.length}
          <BuildMap change={change?.id ?? null} bbox={change?.largest_patch_bbox ?? change?.bbox ?? null} overview={change?.largest_patch_bbox ? change.bbox : null} {tilesBase} compare={step?.compare ?? null} stepChanges={unitChanges} parents={[...new Set(change?.values?.flatMap((v) => v.un_objectid ?? []) ?? [])]} labels={step?.labels ? stepChanges(step).map((c) => c.id) : []} cells={step ? stepChanges(step).filter((c) => c.type === "cell_island" || c.review).map((c) => c.id) : []} legend={step?.legend ?? []} {border} sweep={compare.sweep} satellite={compare.basemap === "satellite"} hasCells={changes.some((c) => c.review)} onpick={(hits: Hit[]) => (compare.hits = hits)} />
        {/if}
        <HitsPanel {compare} inset={0} />
      </div>
    </div>
  </div>
{/if}

<style>
  .app {
    display: flex;
    flex-direction: column;
    height: 100vh;
  }
  .bar {
    display: flex;
    flex-shrink: 0;
    gap: 1rem;
    justify-content: space-between;
    align-items: center;
    height: 3.5rem;
    padding: 0 1.5rem;
    border-bottom: 1px solid var(--brand-grey--border);
  }
  .heading {
    display: flex;
    gap: 1rem;
    align-items: center;
  }
  .title {
    font-family: var(--brand-font-heading);
    font-size: 1.125rem;
    font-weight: 700;
    color: var(--brand-primary--text);
  }
  .body {
    display: flex;
    flex: 1;
    min-height: 0;
  }
  aside {
    --dur-leave: 180ms;
    --dur-enter: 320ms;
    --ease-enter: cubic-bezier(0.05, 0.7, 0.1, 1);
    --ease-in: cubic-bezier(0.55, 0, 1, 0.45);
    flex: 0 0 26rem;
    overflow-y: auto;
    padding: 1rem;
    border-right: 1px solid var(--brand-grey--border);
    font-size: 0.8125rem;
  }
  section {
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--cd-grey--300);
  }
  .step {
    display: flex;
    gap: 0.5rem;
    align-items: center;
    width: 100%;
    padding: 0;
    border: 0;
    background: none;
    color: inherit;
    font-size: 0.9375rem;
    font-weight: 600;
    text-align: left;
    cursor: pointer;
  }
  .step::after {
    content: "›";
    margin-left: auto;
    color: var(--brand-primary--text);
    font-size: 1.125rem;
    line-height: 1;
    transition: transform var(--dur-enter) var(--ease-enter);
  }
  .open .step::after {
    transform: rotate(90deg);
  }
  @media (hover: hover) and (pointer: fine) {
    .step:hover {
      color: var(--brand-primary--text);
    }
  }
  .drawer {
    display: grid;
    grid-template-rows: 0fr;
    transition: grid-template-rows var(--dur-leave) var(--ease-in);
  }
  .open .drawer {
    grid-template-rows: 1fr;
    transition: grid-template-rows var(--dur-enter) var(--ease-enter);
  }
  .drawer-body {
    min-height: 0;
    overflow: hidden;
  }
  @media (prefers-reduced-motion: reduce) {
    .drawer,
    .open .drawer,
    .step::after {
      transition: none;
    }
  }
  .n {
    display: inline-flex;
    justify-content: center;
    width: 1.4rem;
    border-radius: 999px;
    background: var(--cd-grey--300);
  }
  .current .n {
    background: var(--brand-primary--text);
    color: var(--cd-white);
  }
  .panel {
    left: 0.75rem;
    width: 13rem;
  }
  .panel h2:first-child {
    margin-top: 0;
  }
  .intro {
    margin: 0 0 0.75rem;
  }
  ul {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li button {
    display: block;
    width: 100%;
    margin-top: 0.25rem;
    padding: 0.4rem 0.5rem;
    border: 1px solid var(--cd-grey--400);
    border-radius: var(--brand-radius--sm);
    background: none;
    color: inherit;
    text-align: left;
    cursor: pointer;
  }
  li button:hover,
  li button.active {
    border-color: var(--brand-primary--text);
    background: var(--cd-grey--300);
  }
  .head {
    display: flex;
    gap: 0.5rem;
  }
  .own {
    display: grid;
    flex: 1;
    grid-template-columns: 1fr 1fr;
    gap: 0.5rem;
    min-width: 0;
  }
  .entity {
    display: flex;
    gap: 0.4rem;
    align-items: baseline;
  }
  .code {
    flex: 0 0 auto;
    padding: 0 0.25rem;
    border: 1px solid var(--cd-grey--400);
    border-radius: var(--brand-radius--sm);
    background: var(--cd-white);
    font-size: 0.75rem;
    font-weight: 600;
  }
  .own-head {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.5rem;
    padding: 0 calc(0.5rem + 1px);
    color: var(--brand-grey--text);
    font-size: 0.75rem;
    font-weight: 600;
  }
  .km2 {
    flex: 0 0 auto;
    min-width: 5.25rem;
    margin-left: auto;
    color: var(--brand-grey--text);
    text-align: right;
  }
  .stage {
    position: relative;
    display: flex;
    flex: 1;
    min-width: 0;
  }
  .legend {
    display: grid;
    gap: 0.25rem;
    font-weight: 500;
  }
  .legend li {
    display: flex;
    gap: 0.4rem;
    align-items: start;
  }
  .chip {
    flex: none;
    width: 1rem;
    height: 1rem;
    border-radius: 2px;
  }
</style>
