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
- [x] **KSBA Public Portal scraper for JCPS Board of Education** — the original plan said BoardDocs; turns out JCPS uses KSBA (`portal.ksba.org`, agency id 89). Items are extracted from outline-numbered (I, II.A, III.B…) spans. ~73-91 items per regular meeting, ~80 attachments.
- [x] Multi-source orchestrator — `--sources primegov,ksba` (both by default).
- [x] Full-year scrape complete: **39 bodies, 192 meetings, 258 extracted-text attachments**. Data committed under `data/`.
- [x] **Astro + Pagefind dashboard in [`/site/`](site/)**: home (recent meetings), per-body, per-meeting (with parsed items + attachments + indexed text), full-text search.
- [ ] KSBA pagination (Phase 1 only fetches page 1 = ~25 most recent JCPS meetings, ~12 months).
- [ ] GitHub Actions cron + Pages deploy.

## Building the dashboard

```bash
cd site
npm install
npm run build       # produces site/dist/ with Pagefind index baked in
npm run preview     # serves site/dist/ at http://localhost:4321
```

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
