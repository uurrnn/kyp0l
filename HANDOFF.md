# Handoff

**kyp0l** — *A standing record of state and city business.* A static dashboard that aggregates Louisville Metro Council, JCPS Board of Education, Kentucky General Assembly, and KY interim joint committee activity from five upstream sources, plus an internal roster of every KY state legislator and Metro Council member. Live at **https://uurrnn.github.io/kyp0l/** • Repo **github.com/uurrnn/kyp0l** (public, default branch `main`).

You're picking this up cold — read this once, then [README.md](README.md) for build/run details and [docs/superpowers/specs/](docs/superpowers/specs/) for the design rationale behind anything that looks weird.

## What it does, in one sentence

Every 6 hours a GitHub Actions cron job scrapes upstream sources, writes JSON to `data/`, rebuilds the Astro site against that JSON, and deploys it to GitHub Pages. The cron auto-commits the new data back to `main` so the repo is also the database. Slow-changing sources (KSBA, LRC interim, people roster) are gated to ≤1×/day inside the orchestrator so we don't hammer them every cron tick.

## The five-minute orientation

```bash
git clone git@github.com:uurrnn/kyp0l.git
cd kyp0l
py -3.14 -m venv .venv
.venv/Scripts/activate          # Windows • use `source .venv/bin/activate` elsewhere
pip install -e ".[dev]"
python -m pytest                 # 35 tests should pass

# Run a scrape locally (only Open States needs a key; LRC + KSBA + PrimeGov are public)
export OPENSTATES_API_KEY=<get one free at openstates.org>
python -m scrapers --sources primegov,ksba,lrc-interim   # always works without a key
python -m scrapers --sources openstates --limit 5        # smoke test
python -m scrapers --ignore-min-interval                  # full sweep, bypassing the 20h gate

# Build the site
cd site
npm install
npm run build                    # produces site/dist/ + site/dist/pagefind/
npm run preview                  # serves at http://localhost:4321
```

## Architecture

```
GH Actions cron (every 6h)
  ├─ scrapers/__main__.py orchestrates 5 sources, gated by per-source min interval
  │   ├─ primegov.py        →  Louisville Metro PrimeGov public JSON API   →  Meeting JSON + PDF text
  │   ├─ ksba.py            →  KSBA Public Portal HTML (JCPS, agency 89)   →  Meeting JSON + page text
  │   ├─ openstates.py      →  Open States v3 REST (KY bills + people)     →  Bill JSON + Person JSON
  │   ├─ lrc_interim.py     →  legislature.ky.gov + apps.legislature.ky.gov →  Meeting JSON + Body + Committee index
  │   └─ metro_council_roster.py →  hand-curated seed file (26 council members) →  Person JSON
  ├─ git auto-commits data/ deltas back to main
  └─ triggers a follow-up build job
        └─ Astro builds dist/ + Pagefind indexes it → Pages deploy
```

Top-level entities living alongside each other in the data model:

- **`Meeting`** (a body's agenda+attachments at a point in time) — used by PrimeGov, KSBA, **and LRC interim**.
- **`Bill`** (a piece of legislation with sponsors, actions, votes) — used by Open States. Bills attach to `body_ids: list[str]` so a bill that's crossed over appears under both KY chambers. `Sponsor.person_id` and `MemberVote.person_id` carry upstream `ocd-person/...` IDs that the site uses to link to legislator profiles.
- **`Person`** (an elected official) — Source `"openstates"` for KY legislators (138), source `"metro-council"` for council members (26 hand-curated). Stored at `data/people/<slug>.json` with a `data/people/_index.json` map of `ocd-person/... → our slug` for fast lookup at site-build time.
- **Committee membership** is indexed at `data/committees/_index.json` — maps each interim committee body_id to its `member_districts: list[str]`. The site does a chamber-aware district join with people data to render "Serves on" on each legislator profile.

The site renders these together: `/body/<slug>` shows that body's meetings *and* its bills. Floor votes nest inside `Bill.votes[]` — they don't get their own URLs. `/person/<slug>` shows a profile with bills sponsored, voting record, contact info, and (for state legislators) interim committee memberships.

The front end is mostly SSR. The home page is a recess-aware dashboard:

- 5 masthead numbers
- 3-column "this week" strip (committee referrals, floor actions, meetings ahead)
- **Hot right now** — top 8 bills by `billHeat()` score (see `site/src/lib/heat.ts`)
- Subject pulse strip
- During recess: a dedicated "KY interim committee activity" rail above local meetings, plus a recess banner explaining session status and pointing at what *is* live
- Recent legislative activity table

`/bills` is the only interactive page — a Preact island (`BillsFilter.tsx`) that fetches `/bills-manifest.json` and filters by subject, status, body. Filter state lives in the URL. Bill detail pages have an SVG chamber-progress stepper (House → Senate → Governor → Law) and expandable vote cards with members grouped by Yea/Nay/Abstain/Not-voting **plus a per-party tally** showing Dem/Rep splits when person_ids resolve.

## Repo layout

```
kyp0l/
├─ scrapers/                        # Python — runs the data ingest
│   ├─ models.py                    # dataclasses: Body, Meeting, AgendaItem, Attachment,
│   │                               #              Bill, Sponsor (+person_id), Action, Vote,
│   │                               #              MemberVote (+person_id), Person
│   ├─ primegov.py                  # Louisville Metro Council + 39 other PrimeGov bodies
│   ├─ ksba.py                      # JCPS Board via portal.ksba.org (HTML scrape, ASP.NET)
│   ├─ openstates.py                # KY bills + /people roster via Open States v3
│   ├─ lrc_interim.py               # KY interim joint committees (21) — HTML scrape
│   ├─ metro_council_roster.py      # Loader for hand-curated council seed file
│   ├─ pdf_extract.py               # pdfminer.six wrapper, sha256 dedup
│   └─ __main__.py                  # orchestrator; --sources, per-source min-interval gate,
│                                   # --ignore-min-interval bypass, state.json bookkeeping
├─ tests/                           # pytest, 35 tests
│   ├─ test_chamber_progress.py     # bill action timeline → chamber state derivation
│   ├─ test_current_status.py       # chamber state → human string
│   ├─ test_lrc_interim_parsing.py  # landing/detail/documents page parsing + index round-trip
│   ├─ test_models.py               # dataclass round-trip (Bill, Sponsor, MemberVote, Person)
│   ├─ test_openstates_parsing.py   # parse_bill against captured live fixtures
│   ├─ test_people.py               # parse_person + person_id capture
│   ├─ test_smoke.py
│   └─ fixtures/                    # captured upstream JSON/HTML, do not regenerate carelessly
├─ data/                            # ~25MB+, the repo-as-DB. Cron writes here.
│   ├─ bodies.json                  # 60+ bodies (Metro Council, JCPS, KY chambers, 21 interim)
│   ├─ state.json                   # last-seen sha + updated_at + per-source last_run_at
│   ├─ bills/<session>/<slug>.json  # 1,737 KY bills today
│   ├─ meetings/<body>/<year>/*.json # ~280+ meetings (Metro Council, JCPS, interim)
│   ├─ attachments/<sha256>.txt     # extracted text from PDFs / KSBA HTML
│   ├─ people/                      # Person JSONs + _index.json + _seed_metro_council.json
│   │   ├─ ky-<lastname>-<firstname>.json   # 138 KY legislators (Open States)
│   │   ├─ metro-council-<slug>.json         # 26 Metro Council members (seed)
│   │   ├─ _index.json              # ocd-person/... → our slug
│   │   └─ _seed_metro_council.json # hand-curated input for council loader
│   └─ committees/_index.json       # body_id → {name, rsn, documents_id, member_districts}
├─ site/                            # Astro 5 + Pagefind static site
│   ├─ src/lib/data.ts              # reads data/, typed accessors. billStatusTone(),
│   │                               # getSessionStatus(), getCommitteesForPerson(),
│   │                               # getPersonByOcdId(), resolvePersonSlug(), etc.
│   ├─ src/lib/heat.ts              # bill heat score; HEAT_WEIGHTS constants
│   ├─ src/lib/featured-subjects.ts # curated 12-subject list for dashboard pulse + heat
│   ├─ src/lib/bills-manifest.ts    # type for the slim bills manifest
│   ├─ src/layouts/Layout.astro     # masthead + nav (Home/Bills/People/Search)
│   ├─ src/styles/{tokens,base,components}.css  # design tokens, resets, components
│   ├─ src/components/
│   │   ├─ ChamberProgress.astro    # SVG horizontal stepper: House→Senate→Governor→Law
│   │   ├─ VoteCard.astro           # vote card with member groups + per-party tally
│   │   └─ BillsFilter.tsx          # the only client-side island (Preact); /bills facets
│   ├─ src/pages/index.astro        # recess-aware dashboard
│   ├─ src/pages/bills.astro        # mounts BillsFilter; rest is SSR
│   ├─ src/pages/people.astro       # roster index, sectioned by body
│   ├─ src/pages/person/[id].astro  # legislator/council profile
│   ├─ src/pages/{body,meeting,bill}/[id].astro
│   ├─ src/pages/bills-manifest.json.ts  # static endpoint; emits dist/bills-manifest.json
│   ├─ src/pages/search.astro       # Pagefind UI, restyled to match
│   └─ astro.config.mjs             # respects BASE_PATH + SITE_URL env vars; preact integration
├─ scratch/                         # throwaway probe scripts; useful for "what does this API return?"
├─ docs/superpowers/                # design specs and implementation plans for non-trivial work
├─ .github/workflows/
│   └─ scrape-build-deploy.yml      # the only workflow; cron + push + manual triggers
├─ pyproject.toml                   # Python deps (requests, beautifulsoup4, lxml, pdfminer.six)
├─ pytest.ini
└─ README.md                        # user-facing summary; this file is for the engineer
```

## Data sources, with their quirks

### PrimeGov — Louisville Metro
- **API:** `GET https://louisvilleky.primegov.com/api/v2/PublicPortal/ListArchivedMeetings?year=YYYY` and `/api/Meeting/getcompiledfiledownloadurl?compiledFileId=N`. Reverse-engineered from the public portal's JS bundles.
- **Auth:** none.
- **40 bodies** discovered automatically via `/api/committee/GetCommitteeesListByShowInPublicPortal`.
- **Quirks:**
  - Operator test events leak into the public feed with titles like `EVENT 3 - NO AUTOSTART`, `TEST 2 FOR SWAGIT STREAMING`. Filtered in `scrapers/primegov.py:_is_upstream_test_event`.
  - There's a `Test Committee` body that gets filtered the same way.
  - HTML agenda exports (`compileOutputType==3`) are auth-gated; only PDFs (`==1`) are public. We pull the PDF and run pdfminer.

### KSBA — JCPS Board of Education
- **URL:** `https://portal.ksba.org/public/Agency.aspx?PublicAgencyID=89` (JCPS = agency 89).
- **Auth:** none.
- **Quirks:**
  - ASP.NET WebForms; pagination uses `__doPostBack` and `__VIEWSTATE`. We currently read **page 1 only** (~25 most recent meetings = ~12 months). Pagination for older history is on the punch list.
  - Agenda items are inline HTML with Roman+letter outlines (`III.A.`). Parser is in `scrapers/ksba._extract_agenda_items`.
  - **HTML pages have time-varying content** (CSRF tokens etc.) so the same meeting fetched twice produces a different sha256. Each scrape genuinely rewrites the corpus file. Dedup-by-sha is doing the right thing — it just doesn't dedup as much as PrimeGov's pure-PDF source.

### Open States — KY General Assembly (bills + legislators)
- **API:** v3 REST at `https://v3.openstates.org`. Docs: https://docs.openstates.org/api-v3/
- **Auth:** `X-API-KEY` header. Free tier; sign up at openstates.org. Stored in GH repo secret `OPENSTATES_API_KEY`.
- **Active session detected** dynamically via `/jurisdictions/ky?include=legislative_sessions` (currently `2026RS`).
- **What we use:**
  - `/bills` paginated — bills, sponsors, actions, votes (with per-member roll calls and `voter.id`).
  - `/people?jurisdiction=ky&include=offices` — full legislator roster with photo, party, district, contact info, and the stable `ocd-person/...` ID that lets us link sponsors + votes to profiles.
- **Quirks:**
  - Free tier has a tighter **per-minute burst limit** than the daily counter suggests; returns 429s. Scraper throttles to ~1 req/sec and retries once on 429 with `Retry-After` backoff.
  - KY events (committee meetings) are sparse on Open States — we use the LRC interim scraper instead.
  - Bill IDs include the chamber slug: `openstates-ky-<session>-<lowercase-identifier>` e.g. `openstates-ky-2026RS-hb15`.
  - **`person.party`** is populated; **`current_role.party`** is empty for KY. The sponsor parser reads from `person.party` first.
  - Open States returns `voter.id` on every member vote, but it's only captured by recent scrapes. Older bill JSONs in `data/bills/` may have `person_id: null` everywhere — they'll be re-fetched and updated on the next scrape cycle.

### LRC interim joint committees
- **Discovery page:** `https://legislature.ky.gov/Committees/interim-joint-committee` — links to ~21 committee detail pages with `?CommitteeRSN=N&CommitteeType=Interim Joint Committee`.
- **Detail page:** `Committee-Details.aspx?CommitteeRSN=N` — gives display name, jurisdiction, **member roster (district numbers)**, and a link to the per-committee CommitteeDocuments app.
- **Documents app:** `https://apps.legislature.ky.gov/CommitteeDocuments/<id>` — every meeting as `<h3>Tuesday, December 9, 2025</h3><ul><li><a href="./<folder>/<file>.pdf">…</a></li></ul>`. Past years archived to `./<year>.html` (we don't follow these in v1).
- **Auth:** none, no JS rendering. Plain `requests` + `BeautifulSoup`.
- **Per meeting:** download the agenda PDF (filename matches `/agenda/i`) and extract text; list every other linked file as an `Attachment` without downloading.
- **Quirks:**
  - **Senate district encoding.** LRC encodes Senate districts as `100 + N` (Senate D27 → "127"). House districts use the bare number. Our `Person.district` is the bare number for both, so the join needs `lrcDistrictCode()` in `site/src/lib/data.ts`. Critical to know if you touch the membership lookup.
  - **CommitteeRSN ≠ CommitteeDocuments id.** They're different numbers (Education: RSN=29, Documents=28). We extract the documents URL from the detail page rather than guess.
  - **BeautifulSoup with lxml lowercases attribute names.** The discovery selector uses `data-committeersn` (lowercase), not `data-committeeRsn` as written on the page.
  - **The current documents page only shows the active interim cycle.** When LRC rotates to 2026 interim in late spring, 2025 meetings move to `./2025.html`. Our scraped JSONs persist locally; new 2025 entries (rare) won't be picked up.

### Metro Council roster
- **Source:** hand-curated `data/people/_seed_metro_council.json` (26 entries: name, district, party, optional photo URL/email/website).
- **No public API.** Wikipedia's "List of members of the Louisville Metro Council" is the easiest authoritative source for verification.
- **Loader:** `scrapers/metro_council_roster.py` — idempotent rewrite from seed; runs as part of the `people` source.
- **Reverify when:** council elections (every 2 years staggered) or visible roster changes. The seed file's header comment notes when it was last updated.

## Common operations

### Run a fresh scrape locally
```bash
# Always pull bot commits first or you'll trip on stale state.json:
git pull --ff-only origin main

export OPENSTATES_API_KEY=<key>
python -m scrapers                                     # gated; skips slow sources within 20h
python -m scrapers --ignore-min-interval               # bypass the gate (manual full sweep)
python -m scrapers --sources openstates,people         # one or two sources
python -m scrapers --sources lrc-interim --bodies lrc-interim-education  # filter to one committee
python -m scrapers --limit 10                          # cap meetings/bills (debugging)
```

### Watch a CI run
```bash
# On Windows Git Bash, set MSYS_NO_PATHCONV=1 or paths get mangled:
MSYS_NO_PATHCONV=1 gh run list --repo uurrnn/kyp0l --limit 5
MSYS_NO_PATHCONV=1 gh run view <run-id> --log-failed
```

### Force a deploy without scraping
Push any change to `scrapers/`, `site/`, `data/`, `pyproject.toml`, or `.github/workflows/`. The `push` event runs build+deploy without scraping. README/HANDOFF-only edits won't trigger a rebuild.

### Trigger a scrape on demand
```bash
MSYS_NO_PATHCONV=1 gh workflow run scrape-build-deploy.yml --repo uurrnn/kyp0l --ref main
```

### Add a new PrimeGov-based jurisdiction
The PrimeGov scraper is parametric on the subdomain (default `louisvilleky`). Pass `--instance <subdomain>`. You'd also need to update `bodies.json` cleanup logic if names collide.

### Rotate the Open States API key
```bash
MSYS_NO_PATHCONV=1 gh secret set OPENSTATES_API_KEY --repo uurrnn/kyp0l --body "<new-key>"
```

### Update the Metro Council roster
Edit `data/people/_seed_metro_council.json`, then either commit (cron will materialise on the next `people` run) or run `python -m scrapers --sources people --ignore-min-interval` locally and commit the resulting `data/people/metro-council-*.json` files.

### Tune the bill heat score
All weights live in `HEAT_WEIGHTS` at the top of `site/src/lib/heat.ts`. Edit weights → rebuild → reload. Components are recency, action density, vote momentum, coalition breadth, milestone boost, and topic salience (see the file for definitions and tuning notes).

### Debug "the site is broken on production"
1. Check the latest workflow run: `gh run list --limit 3`. If it's red, look at the failed step logs.
2. If the site renders but links 404, check `site/astro.config.mjs` and confirm `BASE_PATH` ends with `/`. There's a normalisation in there — don't remove it.
3. If a specific body or meeting page is missing, look in `data/meetings/<body-slug>/<year>/` for the JSON. If it's not there, the scrape didn't pick it up — check `data/state.json["meetings"]` for the last-seen sha and `data/state.json["sources"]` for the last_run_at.
4. If sponsor/voter names show as plain text instead of links, the bill JSON pre-dates the `person_id` capture. Trigger a manual workflow run (above) and the scrape will rewrite bills with `person_id` populated.

## Running tests
```bash
.venv/Scripts/python.exe -m pytest -v
```
35 tests covering data shapes, parsers, and round-trips. Live HTTP behaviour is covered by captured fixtures in `tests/fixtures/` rather than mocking — re-capture only when an upstream actually changes shape. Site code isn't unit-tested; we rely on `npm run build` for type-checking and on the `dist/` HTML for behavioural checks.

## Punch list (open work, prioritised roughly)

1. **Custom domain.** Currently at `uurrnn.github.io/kyp0l/`. Adding a CNAME would be 30 minutes; site already respects the `SITE_URL` env var.
2. **KSBA section extraction.** The JCPS meeting page renders as one flat list because the parser doesn't populate `AgendaItem.section`. PrimeGov sections work today. Worth a parser pass on `scrapers/ksba.py:_extract_agenda_items`.
3. **KSBA pagination** to cover JCPS Board history beyond the most-recent ~25 meetings. Requires implementing ASP.NET `__doPostBack` form submission. Plan-level work.
4. **LRC documents archived-year pages.** Each committee has `./<year>.html` for past interim periods. The current scraper only fetches the live page; archived years (mostly 2024 and earlier) are not ingested.
5. **Refresh interim committee rosters** when the 2027 interim cycle starts (typically May–June 2026). Member assignments change every interim; the cached `_index.json` member lists go stale.
6. **Search ranking tuning.** Pagefind defaults are fine; bills + meetings + people appear together with no weight on title vs body. Worth a pass.
7. **Email digest / RSS.** Original plan listed both as Phase 2+. Cheap to add since data is already structured.
8. **Sortable bills table.** `/bills` table currently sorts only by last-action-date desc. Adding clickable column headers is a small Preact change.
9. **Faceted-URL deep links from anywhere.** Sponsor names → `/bills?sponsor=…` once the manifest carries sponsor identifiers.
10. **Full bill text.** Open States exposes `versions[]` URLs to bill PDFs; we could pull and pdfminer them like PrimeGov agendas. Big jump in storage + index size.
11. **Historical legislative sessions.** Currently active session only. Open States has KY going back ~a decade.
12. **Federal coverage** of KY's congressional delegation (2 senators + 6 reps). Out of scope for v1; would use unitedstates/congress-legislators on GitHub or Congress.gov API.
13. **Per-vote URLs and deep links.** Currently votes nest in bill pages. A `/vote/<bill>/<n>` route would let people share "look how Sen. X voted on HB 15".
14. **Find-your-legislators by address.** Open States has `/people.geo?lat=&lng=`. Add a small client-side form with a free geocoder (Nominatim/OSM).
15. **Whisper transcripts of committee/council video.** PrimeGov meetings carry video URLs; cloud Whisper costs ~$0.006/min. Costs real money so worth a careful gate.

## Gotchas the next person will hit

- **Windows Git Bash mangles `gh api` paths.** Always prefix `MSYS_NO_PATHCONV=1` for `gh api` calls and `--body /something` flags. Doesn't matter on macOS/Linux.
- **`data/` is committed (repo-as-DB).** The cron auto-commits its updates back to main as the "Louisville Politics Bot" user. After bot commits land, **always `git pull --ff-only origin main` before running the scraper locally** or you'll have to merge.
- **Per-source minimum interval gate** in `scrapers/__main__.py`. KSBA, LRC interim, and the people roster default to ≤1×/20h. The cron's bare `python -m scrapers` picks up the gating; pass `--ignore-min-interval` for manual full sweeps. Last-run timestamps live in `state.json["sources"]`.
- **`OPENSTATES_API_KEY` empty string is a soft skip, not an error.** Workflow stays green even before the secret is configured. Check first that the secret is populated: `gh secret list --repo uurrnn/kyp0l`.
- **`base_path` from `actions/configure-pages` lacks a trailing slash.** The astro.config normalisation handles it. Don't remove that one-liner; it'll silently break every internal link on prod.
- **Open States burst limits** are tighter than the daily limit suggests. The throttle in `scrapers/openstates.OpenStatesScraper._get` is load-bearing; don't optimise it away unless you actually upgrade to a paid tier.
- **Astro 5 BASE_URL behaviour.** `import.meta.env.BASE_URL` reflects the `base` config verbatim — Astro doesn't normalise it. Hence the explicit trailing-slash fix.
- **`@astrojs/preact` is pinned to `^4.1.3`.** Versions 5.x of the integration target Vite 7 / Astro 6 and fail to resolve `astro:preact:opts` against Astro 5.18's bundled Vite 6. If you upgrade Astro to 6.x, bump `@astrojs/preact` to 5.x at the same time.
- **`chamber_progress.governor` can be `null` even when a bill became law.** Some bills are delivered to the Secretary of State without an explicit `executive-signature` action. **Always use `billStatusTone()` from `site/src/lib/data.ts` for status decisions** instead of inspecting `chamber_progress` directly — it consults the actions list and gets these cases right.
- **`/bills` URL params use repeated `?subject=A&subject=B`, not comma-joined.** Many subject names contain commas (e.g. "Education, Elementary And Secondary"). Don't "simplify" it back to a single CSV param.
- **`featured-subjects.ts` is hand-curated.** 12 policy-relevant subjects. Re-evaluate when a new dominant policy area appears in upstream data — it's not auto-derived. Same list is used by both the dashboard subject pulse and the heat score's `topicSalience` component.
- **The `/bills` filter is the only client-side JS island.** Everything else is SSR + tiny inline `<script>` tags. Adding a Preact island anywhere causes the runtime to ship — watch the homepage bundle size.
- **LRC encodes Senate districts as 100+N.** Senate D27 → "127", House districts use the bare number. The site translates via `lrcDistrictCode()` in `site/src/lib/data.ts:getCommitteesForPerson`. Don't refactor that into a single shared key without preserving the chamber-aware logic.
- **BeautifulSoup with `lxml` lowercases attribute names.** The LRC landing parser uses `data-committeersn` (not `data-committeeRsn` as in the page source). Caused real grief once.
- **`getSessionStatus()` checks `last_action_date`** of the most recent bill against a 7-day cutoff. If you're testing the recess banner during an active session and want to see it, edit `RECESS_DAYS` temporarily — don't try to back-date data.
- **Person `id` slugs are stable but not pretty.** KY: `ky-firstname-lastname`. Council: `metro-council-firstname-lastname`. Collisions get a `-2`/`-3` suffix. The `data/people/_index.json` is the source of truth for `ocd-person/... → slug` lookups; don't bypass it by name-matching.
- **Sponsor and voter `person_id` are nullable.** Bills scraped before person_id capture have `null` everywhere — UIs degrade to plain text. Bills scraped after have populated IDs and become clickable. The graceful-degradation pattern (`resolvePersonSlug() ?? plain text`) is everywhere this matters; preserve it.
- **The bot account writes commits as `Louisville Politics Bot <actions@users.noreply.github.com>`.** That's intentional — `GITHUB_TOKEN`-pushed commits don't trigger workflows (GH guard), so the auto-commit from the scrape step doesn't loop into another scrape.

## Where to learn more

- **README.md** — quick build instructions for users.
- **docs/superpowers/specs/2026-05-03-kentucky-state-legislature-design.md** — design rationale for the bills addition. Includes the `chamber_progress` state machine.
- **docs/superpowers/plans/2026-05-03-kentucky-state-legislature.md** — task-by-task plan that produced bills.
- **`site/src/styles/{tokens,base,components}.css`** — the entire design system in three files. Tokens first (colors, type scale, spacing), then resets, then components. No framework, no preprocessor.
- **`site/src/lib/data.ts`** — every typed accessor. `billStatusTone()`, `getSessionStatus()`, `getCommitteesForPerson()`, `getPersonByOcdId()`, `resolvePersonSlug()` are the load-bearing helpers; read them before touching status/identity logic anywhere.
- **`site/src/lib/heat.ts`** — bill heat score with documented weights and tuning notes. Top of file is `HEAT_WEIGHTS`.
- **`site/src/components/BillsFilter.tsx`** — the only client island. Read it end-to-end if you're touching `/bills` or adding a second island; the URL-state pattern is worth copying.
- **scratch/probe_*.py** — small scripts that document how each upstream API/site was reverse-engineered.
- **`git log --oneline`** — commit history is reasonably narrative; commit bodies explain *why*, not just *what*. The recent series (politicians → heat score → recess-aware → LRC interim → interval gating → memberships+party breakdown) is a tight progression worth skimming if you're picking up cold.

## Contact

Repo owner: `uurrnn` on GitHub. Cron secret (`OPENSTATES_API_KEY`) is in the repo's Settings → Secrets and variables → Actions. If you take over and want to rotate the key, do that first.
