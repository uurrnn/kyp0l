import { defineConfig } from "astro/config";

// SITE_URL: deploy origin, e.g. https://<user>.github.io  (no trailing slash)
// BASE_PATH: path prefix, e.g. "/louisville-politics-tracker/" (with leading + trailing slash)
//            Empty / "/" for user-pages-style root deploys.
//
// In GitHub Actions, the configure-pages action exposes these as
// `steps.pages.outputs.origin` and `steps.pages.outputs.base_path`. Locally
// they default to friendly values that work with `astro dev` / `astro preview`.
const SITE_URL = process.env.SITE_URL ?? "http://localhost:4321";
const BASE_PATH = process.env.BASE_PATH || "/";

export default defineConfig({
  site: SITE_URL,
  base: BASE_PATH,
  trailingSlash: "ignore",
  build: {
    format: "directory",
  },
  outDir: "./dist",
});
