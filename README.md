# Louisville Local Politics Tracker

Searchable, daily-updated dashboard of Louisville Metro / Jefferson County local government activity.

**Phase 1 (current):** Louisville Metro Council + JCPS Board of Education.

## Stack

- Python scrapers (`civic-scraper` for PrimeGov, custom for BoardDocs)
- JSON files in `/data/`
- Astro + Pagefind static site in `/site/`
- GitHub Actions cron, GitHub Pages hosting

## Status (Phase 1 in progress)

- [x] PrimeGov public-API scraper — replaces `civic-scraper` since the direct API turned out cleaner and supports all 40 public-portal bodies, not just Metro Council.
- [x] PDF agenda fetch + pdfminer text extraction + sha256 dedup.
- [x] Best-effort agenda-item parser for the Metro Council "N. ID YY-NNNN <title>" format.
- [x] Smoke-tested: 3 Metro Council meetings written to `data/meetings/metro-council/2026/`.
- [ ] Run full-year scrape across all 40 bodies and inspect output.
- [ ] JCPS BoardDocs scraper.
- [ ] Astro + Pagefind dashboard in `/site/`.
- [ ] GitHub Actions cron + Pages deploy.

See [scratch/](scratch/) for the throwaway probes that established the API surface — useful breadcrumbs.

## Local dev

```bash
py -3.14 -m venv .venv
.venv/Scripts/activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -e ".[dev]"
python -m scrapers --year 2026 --bodies metro-council --limit 3
```

The design plan lives at `C:\Users\uurrn\.claude\plans\i-need-to-justify-kind-garden.md`.
