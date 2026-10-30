import svelte from "@astrojs/svelte";
import { defineConfig } from "astro/config";

// "/<repo>" for GitHub's project-pages subpath, set by the deploy workflow.
const base = process.env.BASE_PATH ?? "";

export default defineConfig({
  site: "https://ocha-dap.github.io",
  base,
  integrations: [svelte()],
});
