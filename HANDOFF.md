# Handoff

A static dashboard that aggregates Louisville Metro Council, JCPS Board of Education, and Kentucky General Assembly activity from three upstream sources. Live at **https://uurrnn.github.io/kyp0l/** • Repo **github.com/uurrnn/kyp0l** (public, default branch `main`).

You're picking this up cold — read this once, then [README.md](README.md) for build/run details and [docs/superpowers/specs/](docs/superpowers/specs/) for the design rationale behind anything that looks weird.

## What it does, in one sentence

Every 6 hours a GitHub Actions cron job scrapes three upstream sources, writes JSON to `data/`, rebuilds the Astro site against that JSON, and deploys it to GitHub Pages. The cron auto-commits the new data back to `main` so the repo is also the database.

## The five-minute orientation

```bash
git clone git@github.com:uurrnn/kyp0l.git
cd kyp0l
py -3.14 -m venv .venv
.venv/Scripts/activate          # Windows • use `source .venv/bin/activate` elsewhere
pip install -e ".[dev]"
python -m pytest                 # 20 tests should pass

# Run a scrape locally (only Open States needs a key)
export OPENSTATES_API_KEY=<get one free at openstates.org>
python -m scrapers --sources primegov,ksba                       # always works
python -m scrapers --sources openstates --limit 5                # smoke test
python -m scrapers                                               # all three, full

# Build the site
cd site
npm install
npm run build                    # produces site/dist/ + site/dist/pagefind/
npm run preview                  # serves at http://localhost:4321
```

## Architecture

```
GH Actions cron (every 6h)
  ├─ scrapers/__main__.py orchestrates 3 sources
  │   ├─ primegov.py  →  Louisville Metro PrimeGov public JSON API     →  Meeting JSON + PDF text
  │   ├─ ksba.py      →  KSBA Public Portal HTML (JCPS, agency 89)     →  Meeting JSON + page text
  │   └─ openstates.py→  Open States v3 REST API (KY bills)            →  Bill JSON
  ├─ git auto-commits data/ deltas back to main
  └─ triggers a follow-up build job
        └─ Astro builds dist/ + Pagefind indexes it → Pages deploy
```

Two top-level entities live alongside each other in the data model:
- **`Meeting`** (a body's agenda+attachments at a point in time) — used by PrimeGov + KSBA
- **`Bill`** (a piece of legislation with sponsors, actions, votes) — used by Open States. Bills attach to `body_ids: list[str]` so a bill that's crossed over appears under both KY chambers.

The site renders both side-by-side: `/body/<slug>` shows that body's meetings *and* its bills. Floor votes nest inside `Bill.votes[]` — they don't get their own URLs.

## Repo layout

```
kyp0l/
├─ scrapers/                    # Python — runs the data ingest
│   ├─ models.py                # dataclasses: Body, Meeting, AgendaItem, Attachment, Bill, Sponsor, Action, Vote, MemberVote
│   ├─ primegov.py              # Louisville Metro Council + 39 other PrimeGov bodies
│   ├─ ksba.py                  # JCPS Board via portal.ksba.org (HTML scrape, ASP.NET)
│   ├─ openstates.py            # KY bills via Open States v3 (JSON, requires OPENSTATES_API_KEY)
│   ├─ pdf_extract.py           # pdfminer.six wrapper, sha256 dedup
│   └─ __main__.py              # orchestrator, --sources flag, state.json bookkeeping
├─ tests/                       # pytest, 20 tests, see "Running tests" below
│   ├─ test_chamber_progress.py # bill action timeline → chamber state derivation
│   ├─ test_current_status.py   # chamber state → human string
│   ├─ test_models.py           # dataclass round-trip
│   ├─ test_openstates_parsing.py # parse_bill against captured live fixtures
│   └─ fixtures/                # captured Open States JSON, do not regenerate carelessly
├─ data/                        # ~21MB, the repo-as-DB. Cron writes here.
│   ├─ bodies.json              # 42 bodies, slug → name + source
│   ├─ state.json               # last-seen sha + updated_at maps for incremental scrapes
│   ├─ bills/<session>/<slug>.json   # 1737 KY bills today
│   ├─ meetings/<body>/<year>/*.json # 192 meetings
│   └─ attachments/<sha256>.txt # extracted text from PDFs / KSBA HTML
├─ site/                        # Astro 5 + Pagefind static site
│   ├─ src/lib/data.ts          # reads /data/, exposes typed accessors
│   ├─ src/layouts/Layout.astro
│   ├─ src/pages/index.astro
│   ├─ src/pages/{body,meeting,bill}/[id].astro
│   ├─ src/pages/{bills,search}.astro
│   └─ astro.config.mjs         # respects BASE_PATH + SITE_URL env vars (CI sets these)
├─ scratch/                     # throwaway probe scripts, useful for "what does this API return?"
├─ docs/superpowers/            # design specs and implementation plans for non-trivial work
│   ├─ specs/2026-05-03-kentucky-state-legislature-design.md
│   └─ plans/2026-05-03-kentucky-state-legislature.md
├─ .github/workflows/
│   └─ scrape-build-deploy.yml  # the only workflow; cron + push + manual triggers
├─ pyproject.toml               # Python deps (requests, beautifulsoup4, lxml, pdfminer.six)
├─ pytest.ini
└─ README.md                    # user-facing summary; this file is for the engineer
```

## Data sources, with their quirks

### PrimeGov — Louisville Metro
- **API:** `GET https://louisvilleky.primegov.com/api/v2/PublicPortal/ListArchivedMeetings?year=YYYY` and `/api/Meeting/getcompiledfiledownloadurl?compiledFileId=N`. Reverse-engineered from the public portal's JS bundles.
- **Auth:** none (public).
- **40 bodies** — Metro Council, BZA, Planning Commission, all the architectural review committees, JCPS hearings, etc. Discovered automatically via `/api/committee/GetCommitteeesListByShowInPublicPortal`.
- **Quirks:**
  - Operator test events leak into the public feed with titles like `EVENT 3 - NO AUTOSTART` and `TEST 2 FOR SWAGIT STREAMING`. Filtered in `scrapers/primegov.py:_is_upstream_test_event`.
  - There's also a `Test Committee` body that gets filtered the same way.
  - HTML agenda exports (`compileOutputType==3`) are auth-gated; only PDFs (`==1`) are public. We pull the PDF and run pdfminer.

### KSBA — JCPS Board of Education
- **URL:** `https://portal.ksba.org/public/Agency.aspx?PublicAgencyID=89` (JCPS = agency 89).
- **Auth:** none.
- **Quirks:**
  - It's an ASP.NET WebForms site; pagination uses `__doPostBack` and `__VIEWSTATE`. We currently read **page 1 only** (~25 most recent meetings = ~12 months). KSBA pagination for older history is on the punch list.
  - Agenda items are inline HTML inside `AgendaItemHeader` divs and outline-numbered spans (Roman + letter, e.g. `III.A.`). Parser is in `scrapers/ksba._extract_agenda_items`.
  - Attachments are direct PDF downloads — public, no auth required.

### Open States — KY General Assembly
- **API:** v3 REST at `https://v3.openstates.org`. Docs: https://docs.openstates.org/api-v3/
- **Auth:** `X-API-KEY` header. Free tier; sign up at openstates.org. Stored in GH repo secret `OPENSTATES_API_KEY`.
- **Active session detected** dynamically via `/jurisdictions/ky?include=legislative_sessions` (currently `2026RS`).
- **Quirks:**
  - Free tier daily limit is high (10K+) but there's a tighter **per-minute burst limit** that returns 429s. Scraper throttles to ~1 req/sec and retries once on 429 with `Retry-After` backoff. This was discovered the hard way.
  - Open States exposes Kentucky **events** (committee meetings) but only ~1 event total at any given time. Not enough to be useful — events are deferred. The `/events` endpoint is wired up in `scrapers/openstates.py` but not called by the orchestrator.
  - Bill IDs from us include the chamber slug: `openstates-ky-<session>-<lowercase-identifier>` e.g. `openstates-ky-2026RS-hb15`.

## Common operations

### Run a fresh scrape locally
```bash
# Always pull bot commits first or you'll trip on stale state.json:
git pull --ff-only origin main

export OPENSTATES_API_KEY=<key>
python -m scrapers                          # all three sources
python -m scrapers --sources openstates     # just one
python -m scrapers --bodies metro-council   # filter to specific body
python -m scrapers --limit 10               # cap for testing
```

### Watch a CI run
```bash
# On Windows Git Bash, set MSYS_NO_PATHCONV=1 or paths get mangled:
MSYS_NO_PATHCONV=1 gh run list --repo uurrnn/kyp0l --limit 5
MSYS_NO_PATHCONV=1 gh run view <run-id> --log-failed
```

### Force a deploy without scraping
Push any change to `scrapers/`, `site/`, `data/`, or `.github/workflows/`. The `push` event runs build+deploy without scraping. README-only edits won't trigger a rebuild.

### Trigger a scrape on demand
```bash
MSYS_NO_PATHCONV=1 gh workflow run scrape-build-deploy.yml --repo uurrnn/kyp0l --ref main
```

### Add a new PrimeGov-based jurisdiction
The PrimeGov scraper is parametric on the subdomain (default `louisvilleky`). Pass `--instance <subdomain>` to use a different city. You'd also need to update `bodies.json` cleanup logic if names collide.

### Rotate the Open States API key
```bash
MSYS_NO_PATHCONV=1 gh secret set OPENSTATES_API_KEY --repo uurrnn/kyp0l --body "<new-key>"
```

### Debug "the site is broken on production"
1. Check the latest workflow run: `gh run list --limit 3`. If it's red, look at the failed step logs.
2. If the site renders but links 404, check `site/astro.config.mjs` and confirm `BASE_PATH` ends with `/`. There's a normalisation in there — don't remove it.
3. If a specific body or meeting page is missing, look in `data/meetings/<body-slug>/<year>/` for the JSON. If it's not there, the scrape didn't pick it up — check `data/state.json` for the last-seen sha.

## Running tests
```bash
.venv/Scripts/python.exe -m pytest -v
```
20 tests covering the bill-shape Python code (data sources have integration-y characteristics that we cover by capturing live fixtures rather than mocking endpoints). Site code isn't unit-tested; we rely on `npm run build` to catch type errors.

## Punch list (open work, prioritised roughly)

1. **Custom domain.** Currently at `uurrnn.github.io/kyp0l/`. Adding a CNAME would be 30 minutes; site already respects the `SITE_URL` env var.
2. **KSBA pagination** to cover JCPS Board history beyond the most-recent ~25 meetings. Requires implementing ASP.NET `__doPostBack` form submission. Plan-level work, not trivial.
3. **Search ranking tuning.** Pagefind defaults are fine; bills + meetings appear together with no weight on title vs body. Worth a pass.
4. **Section grouping on meeting pages.** The KSBA meetings list ~80 items in a flat list. Grouping by section ("Action Items", "Consent Calendar") would help scanning.
5. **Email digest / RSS.** Original plan listed both as Phase 2+. Cheap to add since data is already structured.
6. **Full bill text.** We index metadata + abstract today. Open States exposes `versions[]` URLs to bill PDFs; we could pull and pdfminer them like PrimeGov agendas. Big jump in storage + index size.
7. **Historical legislative sessions.** Currently active session only. Open States has KY going back ~a decade.
8. **KY committee events scraper.** Open States returns ~1 event for KY at a time; if coverage improves, the scraper class already has `list_events()` and `_parse_event` patterns to extend. Otherwise, scrape the LRC committee calendar directly.
9. **Federal coverage** of KY's congressional delegation (2 senators + 6 reps). Out of scope for v1; would use a different API (ProPublica / Congress.gov).
10. **Per-vote URLs and deep links** — currently votes nest in bill pages. If folks want to share "look how Sen. X voted on HB 15", a `/vote/<bill>/<n>` route is cheap.

## Gotchas the next person will hit

- **Windows Git Bash mangles `gh api` paths.** Always prefix `MSYS_NO_PATHCONV=1` for `gh api` calls and `--body /something` flags. Doesn't matter on macOS/Linux. Documented in memory.
- **`data/` is gitignored protection was removed for the repo-as-DB pattern.** It's now committed. The cron auto-commits its updates back to main as the "Louisville Politics Bot" user. After bot commits land, **always `git pull --ff-only origin main` before running the scraper locally** or you'll have to merge.
- **`OPENSTATES_API_KEY` empty string is a soft skip, not an error.** This was deliberate so the workflow stays green even before the secret is configured. If you find Open States data isn't updating, check first that the secret is actually populated: `gh secret list --repo uurrnn/kyp0l`.
- **`base_path` from `actions/configure-pages` lacks a trailing slash.** The astro.config normalisation handles it. Don't remove that one-liner; it'll silently break every internal link on prod.
- **KSBA HTML pages have time-varying content** (CSRF tokens, etc.) so the same meeting fetched twice produces a different sha256. Each scrape genuinely rewrites the corpus file. The dedup-by-sha is doing the right thing — it just doesn't dedup as much as PrimeGov's pure-PDF source.
- **Open States burst limits** are tighter than the daily limit suggests. The throttle in `scrapers/openstates.OpenStatesScraper._get` is load-bearing; don't optimise it away unless you actually upgrade to a paid tier.
- **Astro 5 BASE_URL behaviour.** `import.meta.env.BASE_URL` reflects the `base` config verbatim — Astro doesn't normalise it. Hence the explicit trailing-slash fix above.

## Where to learn more

- **README.md** — quick build instructions for users.
- **docs/superpowers/specs/2026-05-03-kentucky-state-legislature-design.md** — design rationale for the bills addition. Includes the chamber_progress state machine.
- **docs/superpowers/plans/2026-05-03-kentucky-state-legislature.md** — full task-by-task implementation plan that produced Phase 3.
- **scratch/probe_*.py** — small scripts that document how each upstream API/site was reverse-engineered. Useful when an upstream changes shape.
- **`git log --oneline`** — commit history is reasonably narrative; commits explain *why*, not just *what*.

## Contact

Repo owner: `uurrnn` on GitHub. Cron secret (`OPENSTATES_API_KEY`) is in the repo's Settings → Secrets and variables → Actions. If you take over and want to rotate the key, do that first.
