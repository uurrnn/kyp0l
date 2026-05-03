import { defineConfig } from "astro/config";

// Static site that consumes /data/ from the parent repo.
// Build output goes to ./dist; Pagefind indexes ./dist after astro build.
export default defineConfig({
  site: "https://example.com", // override via GH Pages config later
  trailingSlash: "ignore",
  build: {
    format: "directory",
  },
  outDir: "./dist",
});
