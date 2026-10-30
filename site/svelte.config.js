/** @type {import('@sveltejs/vite-plugin-svelte').SvelteConfig} */
// hmr off: hot-swapping App.svelte detaches later component updates, so every save reloads the page.
export default { compilerOptions: { runes: true, hmr: false } };
