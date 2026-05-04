import { defineConfig } from "astro/config";
import preact from "@astrojs/preact";

// SITE_URL: deploy origin, e.g. https://<user>.github.io  (no trailing slash)
// BASE_PATH: path prefix, e.g. "/louisville-politics-tracker/" (with leading + trailing slash)
//            Empty / "/" for user-pages-style root deploys.
//
// In GitHub Actions, the configure-pages action exposes these as
// `steps.pages.outputs.origin` and `steps.pages.outputs.base_path`. Locally
// they default to friendly values that work with `astro dev` / `astro preview`.
const SITE_URL = process.env.SITE_URL ?? "http://localhost:4321";
// Normalise: GitHub's actions/configure-pages exposes `base_path` like
// `/kyp0l` (no trailing slash). Astro respects whatever we pass in, so an
// unterminated base produces hrefs like `/kyp0lbills`. Force a trailing
// slash so `${import.meta.env.BASE_URL}bills` always renders correctly.
const RAW_BASE = process.env.BASE_PATH || "/";
const BASE_PATH = RAW_BASE.endsWith("/") ? RAW_BASE : `${RAW_BASE}/`;

export default defineConfig({
  site: SITE_URL,
  base: BASE_PATH,
  trailingSlash: "ignore",
  integrations: [preact()],
  build: {
    format: "directory",
  },
  outDir: "./dist",
});
