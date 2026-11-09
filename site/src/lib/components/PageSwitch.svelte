<script lang="ts">
  const PAGES = [
    { id: "explorer", label: "Explorer", href: "/" },
    { id: "build", label: "Build", href: "/build" },
  ];
  let { current }: { current: "explorer" | "build" } = $props();
</script>

<nav class="pages" aria-label="Pages">
  {#each PAGES as p (p.id)}
    <a href={p.href} aria-current={p.id === current ? "page" : undefined}>{p.label}</a>
  {/each}
</nav>

<style>
  .pages {
    display: flex;
    flex-shrink: 0;
    border: 1px solid var(--cd-grey--500);
    border-radius: var(--brand-radius--sm);
    overflow: hidden;
  }
  a {
    padding: 0.3rem 0.6rem;
    background: var(--cd-white);
    color: var(--cd-grey--800);
    font-size: 0.75rem;
    font-weight: 500;
    text-decoration: none;
  }
  a + a {
    border-left: 1px solid var(--cd-grey--400);
  }
  a:hover:not([aria-current]) {
    background: var(--cd-grey--300);
  }
  a[aria-current="page"] {
    background: var(--brand-primary--text);
    color: var(--cd-white);
  }
</style>
