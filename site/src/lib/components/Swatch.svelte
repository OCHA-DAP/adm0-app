<script lang="ts">
  import type { Kind } from "$lib/compare.svelte";

  let { kind, color, dashed = false }: { kind: Kind; color: string; dashed?: boolean } = $props();
</script>

<span class="swatch {kind}" class:dashed style:--color={color}></span>

<style>
  .swatch {
    display: inline-block;
    width: 0.9rem;
    height: 0.9rem;
    margin-right: 0.3rem;
    border: 2px solid var(--color);
    background: color-mix(in srgb, var(--color) 15%, transparent);
    vertical-align: middle;
  }
  .dashed {
    border-style: dashed;
  }
  .line {
    height: 0;
    border-width: 2px 0 0;
  }
</style>
