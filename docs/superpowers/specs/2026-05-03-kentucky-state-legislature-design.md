# Kentucky State Legislature — Design Spec

**Date:** 2026-05-03
**Status:** Design approved interactively; file pending user review
**Repo:** [uurrnn/kyp0l](https://github.com/uurrnn/kyp0l) • Live site: https://uurrnn.github.io/kyp0l/

## Context

The current tracker covers Louisville Metro Council (PrimeGov) and JCPS Board (KSBA Public Portal). Both produce *meetings* with agendas. The user wants to expand scope to the **Kentucky state legislature** — bills, committee meetings, and floor votes — without losing the existing local coverage.

Bills are a fundamentally different entity shape from meetings: long-lived, with sponsors, status transitions, and roll-call vote history. They don't fit cleanly into the existing `Body → Meeting → AgendaItem` model and shouldn't be force-fit. This spec adds bills as a parallel top-level entity while reusing the meeting model for committee events.

The site is also rebranding from "Louisville Local Politics" to **"Kentucky + Louisville Politics"** to reflect the expanded scope.

## Scope

**In scope (Phase 3):**
- Kentucky General Assembly bills + resolutions, *current session only*, metadata + abstract + actions + votes (no full bill text in this phase).
- Floor votes — folded into each bill's `votes[]` field, including per-member roll-call data when Open States provides it.
- Committee meetings of the KY Senate and KY House — pulled from Open States `/events`, mapped into the existing `Meeting` shape.
- Two new bodies (`ky-senate`, `ky-house`) plus committee bodies created lazily when seen in events feed. Committee body slugs follow `slugify(committee_name)` (matching the existing PrimeGov/KSBA convention), e.g. a Senate Judiciary committee event creates `ky-senate-committee-on-judiciary`.
- Site changes: `/bill/[id]`, `/bills` index, updates to `/body/[id]` and `/` to surface bill activity.
- Workflow change: scraper picks up `OPENSTATES_API_KEY` from env (GH repo secret in CI, env var locally).

**Out of scope (deferred):**
- Full bill text (PDFs / versions) — one-click reach via the LRC source link is acceptable for v1.
- Historical sessions — only the current active session, identified dynamically from Open States' jurisdictions endpoint.
- U.S. Congress (federal) coverage of KY's delegation.
- Direct LRC scraping. Open States is the sole source for state data. If event coverage proves too thin, an LRC fallback is a future phase, not blocking.
- Per-vote URLs (`/vote/[id]`). Votes nest inside their bill page.
- Per-session URLs (`/session/[id]`). Out of scope.
- Email digest, RSS, search ranking tuning — listed in the existing punch list.

## Data sources

**Open States API** (https://docs.openstates.org/api-v3/):
- `GET /v3/jurisdictions/ky/?include=legislative_sessions` — find active session.
- `GET /v3/bills/?jurisdiction=ky&session=<slug>` with `include` params — list + detail in one call (Open States supports `?include=` query params to inline child resources; exact accepted values to be confirmed against live docs at implementation time).
- `GET /v3/events/?jurisdiction=ky` with `include` params — committee meetings.

Authentication: API key in `OPENSTATES_API_KEY` env var, sent as a header per Open States' current docs (the auth header name has been `X-API-KEY` historically; verify before first call). Free tier ceiling is in the low thousands of requests per day — the daily scrape budget should sit well under that thanks to `updated_at`-based skipping. If the live limit is tighter than expected, drop to a 12h cron rather than reduce coverage.

Fallback if Open States event coverage is unusable for KY: defer events to a later phase, ship bills only. Spec does not mandate an LRC scraper.

## Data model

Two new entity types live alongside the existing `Body` / `Meeting` / `AgendaItem` / `Attachment`. New types are defined in `scrapers/models.py`:

```python
@dataclass
class Bill:
    id: str                       # "openstates-ky-2026rs-hb15"
    body_ids: list[str]           # ["ky-house"], plus ["ky-senate"] once received
    session: str                  # "2026rs"
    identifier: str               # "HB 15"
    title: str
    abstract: str | None
    classification: list[str]     # ["bill"] | ["resolution"] | ["constitutional-amendment"]
    sponsors: list[Sponsor]
    actions: list[Action]
    votes: list[Vote]
    subjects: list[str]
    chamber_progress: dict        # {"lower": "passed"|"in_committee"|null, "upper": ..., "governor": ...}
    current_status: str           # human-readable summary derived from chamber_progress
    last_action_date: str         # ISO date, used for sorting
    source_url: str               # LRC canonical URL
    openstates_id: str            # "ocd-bill/<uuid>" for re-fetch

@dataclass
class Sponsor:
    name: str
    party: str | None
    district: str | None
    primary: bool

@dataclass
class Action:
    date: str                     # ISO
    description: str
    chamber: str | None           # "lower" | "upper" | None
    classification: list[str]     # Open States action types (e.g. "passage", "committee-passage")

@dataclass
class Vote:
    motion: str
    date: str
    chamber: str                  # "lower" | "upper"
    result: str                   # "pass" | "fail"
    counts: dict                  # {"yes": int, "no": int, "abstain": int, "not voting": int}
    member_votes: list[MemberVote]

@dataclass
class MemberVote:
    name: str
    option: str                   # "yes" | "no" | "abstain" | "not voting"
```

`chamber_progress` derivation, walking `actions[]` chronologically and writing the most-progressed state per chamber:

| Open States action classification | Sets `chamber_progress[chamber]` to |
|---|---|
| `introduction` | `"introduced"` |
| `referral-committee` | `"in_committee"` |
| `committee-passage` (any flavor) | `"passed_committee"` |
| `passage` | `"passed"` |
| `failure` | `"failed"` |
| `executive-signature` | sets `governor: "signed"` |
| `executive-veto` | sets `governor: "vetoed"` |

A chamber's value is `null` when no action has touched it yet. Progress is monotonic — once `"passed"` we don't downgrade to `"in_committee"` even if a later action is a recommittal.

`current_status` is a one-line human-readable summary computed from `chamber_progress`. Examples:
- `{"lower": "passed", "upper": "in_committee", "governor": null}` → `"Passed House, in Senate committee"`
- `{"lower": "introduced", "upper": null, "governor": null}` → `"Introduced in House"`
- `{"lower": "passed", "upper": "passed", "governor": "signed"}` → `"Signed by governor"`
- `{"lower": "failed", "upper": null, "governor": null}` → `"Failed in House"`

## File layout

```
data/
  bills/
    2026rs/
      ky-hb15.json
      ky-hb16.json
      ...
  meetings/                            # unchanged for existing bodies
    ky-senate-committee-on-judiciary/
      2026/openstates-<event-id>.json
    ...
  bodies.json                          # adds ky-senate, ky-house, lazy committees
  state.json                           # adds bills_updated_at map
  attachments/                         # unchanged; events get corpus files like KSBA
```

## Scraper architecture

New module: `scrapers/openstates.py`. Mirrors the shape of `scrapers/primegov.py`:

```python
class OpenStatesScraper:
    def __init__(self, api_key: str, jurisdiction: str = "ky"): ...
    def current_session(self) -> str: ...                    # "2026rs"
    def list_bills(self, session: str) -> Iterator[dict]: ...
    def fetch_bill(self, raw: dict) -> Bill: ...
    def list_events(self) -> Iterator[dict]: ...
    def fetch_event(self, raw: dict, body: Body) -> Meeting: ...
```

Orchestrator (`scrapers/__main__.py`) gains a third source: `--sources primegov,ksba,openstates` (default all three). Behavior:

1. Read `OPENSTATES_API_KEY` from env. If missing, skip the openstates source with a printed warning rather than failing — local dev without a key still works.
2. Fetch active session, then paginate bills (~75 pages × 20 bills = ~1500 bills for a regular session).
3. For each bill: compare `updated_at` to `state["bills_updated_at"][id]`. Skip if unchanged.
4. Build `Bill` from raw, including derived `chamber_progress` + `current_status`.
5. Write to `data/bills/<session>/<bill-id>.json`. Update state.
6. Same dance for events → `data/meetings/<lazy-body>/<year>/openstates-<id>.json`.

**Rate-limit handling:** check `X-RateLimit-Remaining` after each call. If <50, `time.sleep(60)`. Hard error on 429.

**Idempotency:** `state.json` keys gain `bills_updated_at: {id: iso_ts}` map and `events_updated_at: {id: iso_ts}` map alongside the existing `meetings: {...}` map.

## Site architecture

[site/src/lib/data.ts](site/src/lib/data.ts) gains parallel functions for bills:

```ts
export interface Bill { ... }   // matches the Python dataclass shape
export interface Sponsor { ... }
export interface Action { ... }
export interface Vote { ... }
export interface MemberVote { ... }

export function getBills(): Bill[]
export function getBillById(id: string): Bill | undefined
export function getBillsByBody(bodyId: string): Bill[]
export function getRecentBills(n: number): Bill[]
```

New pages:

- [site/src/pages/bill/[id].astro](site/src/pages/bill/[id].astro) — title, abstract, status strip, sponsors, actions timeline, collapsible vote cards.
- [site/src/pages/bills.astro](site/src/pages/bills.astro) — index sorted by `last_action_date` desc, with client-side filter chips for chamber + status.

Updated pages:

- [site/src/pages/body/[id].astro](site/src/pages/body/[id].astro) — adds a "Bills" section beneath "Meetings" when `getBillsByBody(body.id)` is non-empty.
- [site/src/pages/index.astro](site/src/pages/index.astro) — adds "Recent legislative activity" section showing 10 most-recent-action bills.
- [site/src/layouts/Layout.astro](site/src/layouts/Layout.astro) — brand becomes "Kentucky + Louisville Politics".

Pagefind: bill pages get `data-pagefind-body` and meta tags (`status`, `chamber`, `session`, `subjects`). Bills become a searchable corpus alongside meetings.

**Build scale impact:** ~233 pages today → ~1700 pages with bills. Astro/Pagefind both linear; build time goes from ~4s to ~3 min. Within GH Actions free-tier comfort.

## Workflow / deployment

[.github/workflows/scrape-build-deploy.yml](.github/workflows/scrape-build-deploy.yml) gains:

```yaml
- name: Scrape (skip on push events that didn't touch data sources)
  if: github.event_name != 'push'
  env:
    PYTHONUNBUFFERED: "1"
    OPENSTATES_API_KEY: ${{ secrets.OPENSTATES_API_KEY }}
  run: |
    python -m scrapers --year "$(date -u +%Y)" --no-upcoming
    python -m scrapers --year "$(date -u +%Y)" --sources primegov
```

User obtains an Open States API key (free signup at openstates.org), then either:
1. Pastes it into the chat for me to set via `gh secret set OPENSTATES_API_KEY --repo uurrnn/kyp0l`, or
2. Sets it themselves in the GH repo Settings → Secrets and variables → Actions.

If the secret is unset, GitHub passes an empty string to the env var. The scraper treats `OPENSTATES_API_KEY=""` (empty or missing) as "skip the openstates source with a printed warning" — PrimeGov + KSBA still run and the workflow still goes green. This makes the change safe to merge before the secret is configured.

## Verification

After implementation, the spec is verified end-to-end by:

1. **Local probe** — `python -c "from scrapers.openstates import OpenStatesScraper; s = OpenStatesScraper(env.OPENSTATES_API_KEY); print(s.current_session()); next(s.list_bills(s.current_session()))"` returns a real bill dict.
2. **Local scrape** — `OPENSTATES_API_KEY=... python -m scrapers --sources openstates --limit 50` writes 50 bill JSONs to `data/bills/2026rs/`.
3. **Bill page render** — `site/dist/bill/ky-hb15/index.html` exists and contains the bill identifier, title, sponsors, status strip, and at least one action.
4. **Body page integration** — `site/dist/body/ky-house/index.html` shows both Meetings and Bills sections; bills include the chamber status badge.
5. **Pagefind** — search query for a known bill subject (e.g. "education") returns at least one bill result distinct from meeting results.
6. **CI dry-run** — push to a branch, watch the workflow set `OPENSTATES_API_KEY`, fetch bills, build site, deploy to a preview env (or just the main env on merge).
7. **Cross-source navigation** — confirm site header rebrand, confirm `/bill/<id>` URLs use the correct base path under `/kyp0l/`.

## Open / risk items

- **Open States KY event coverage** — historically variable. Probe at implementation time: if events returned for the active session look thin or noticeably stale relative to the official LRC committee calendar, defer events to a follow-up phase and ship bills-only. Calling out a specific count threshold here is a false precision; judge at the implementation step.
- **Active session detection at session boundaries** — between sessions, `current_session()` should return the most recently ended session so we don't 404. Cover with a fallback in the scraper.
- **Bill volume during peak session** — during a session's first 30 days, KY can introduce 100+ bills/day. The 6h cron covers this comfortably; flagged here so we don't reduce cadence later without thinking about it.
- **Pagefind index size** — ~1500 bills × ~2KB indexable text = ~3MB index. Still in browser-comfortable territory.
