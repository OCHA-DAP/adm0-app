import svelte from "@astrojs/svelte";
import { defineConfig } from "astro/config";
import { loadEnv } from "vite";

// "/<repo>" for GitHub's project-pages subpath, set by the deploy workflow.
const base = process.env.BASE_PATH ?? "";

export default defineConfig({
  site: "https://ocha-dap.github.io",
  base,
  integrations: [svelte()],
  vite: {
    plugins: [
      {
        // The dev server unlocks itself from the repo-root .env; builds never see the password.
        name: "dev-password",
        apply: "serve",
        config: () => ({ define: { "import.meta.env.DEV_PASSWORD": JSON.stringify(loadEnv("", "..", "SITE_").SITE_PASSWORD ?? "") } }),
      },
    ],
  },
});
