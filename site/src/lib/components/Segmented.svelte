<script lang="ts">
  let {
    label,
    options,
    current,
    stretch = false,
    pick,
  }: {
    label: string;
    options: { id: string; label: string; swatch?: string }[];
    current: string;
    stretch?: boolean;
    pick: (id: string) => void;
  } = $props();
</script>

<div class="segmented" class:stretch role="radiogroup" aria-label={label}>
  {#each options as o (o.id)}
    <button type="button" role="radio" aria-checked={current === o.id} class:active={current === o.id} onclick={() => pick(o.id)}>{#if o.swatch}<span class="swatch" style:background={o.swatch}></span>{/if}{o.label}</button>
  {/each}
</div>

<style>
  .segmented {
    display: flex;
    border: 1px solid var(--cd-grey--500);
    border-radius: var(--brand-radius--sm);
    overflow: hidden;
    background: var(--cd-white);
  }
  button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.35rem;
    padding: 0.3rem 0.6rem;
    border: none;
    border-left: 1px solid var(--cd-grey--400);
    background: var(--cd-white);
    color: var(--cd-grey--800);
    font-size: 0.75rem;
    font-weight: 500;
    cursor: pointer;
  }
  .stretch button {
    flex: 1 1 0;
  }
  button:first-child {
    border-left: none;
  }
  button:hover:not(.active) {
    background: var(--cd-grey--300);
  }
  button.active {
    background: var(--brand-primary--text);
    color: var(--cd-white);
  }
  .swatch {
    width: 0.7rem;
    height: 0.7rem;
    border: 1px solid var(--cd-grey--500);
    border-radius: 2px;
  }
</style>
