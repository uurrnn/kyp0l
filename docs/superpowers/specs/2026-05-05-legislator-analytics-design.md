# Legislator Analytics — Design Spec

**Date:** 2026-05-05
**Status:** Design approved interactively
**Repo:** [uurrnn/kyp0l](https://github.com/uurrnn/kyp0l) • Live site: https://uurrnn.github.io/kyp0l/

## Context

kyp0l already has rich Open States data (1,737 KY bills with sponsors, actions, and per-member roll-call votes) and 138 legislator profiles, but the profile pages just list bills sponsored and votes cast — there's no aggregate signal. This spec adds derived per-legislator metrics (sponsorship counts, party loyalty %, effectiveness %, top subjects, top co-sponsors), surfaces them on three places (profile pages, a new `/scorecards` leaderboard, a new `/compare` side-by-side), and ships entirely as build-time derivation with no new scrape and no new committed artifact.

## Scope

**In scope:**
- Per-legislator stats for KY state legislators only (138 people; KY House + KY Senate).
- Three UI surfaces: enriched `/person/<slug>` profile pages, new `/scorecards` leaderboard, new `/compare` side-by-side.
- All metrics derived at site build time from existing `data/bills/` and `data/people/` JSON; no scrape, no commit.

**Out of scope:**
- Council scorecards — Metro Council has no vote/sponsor data.
- Coalition graph visualisation — top co-sponsors list is the v1 surface.
- Bipartisan score beyond the inverse of party loyalty.
- Trends across sessions — current session only.
- Effectiveness weighting by bill significance.
- New client-side islands — `/scorecards` and `/compare` are SSR with URL-state forms.

## Architecture

```
data.ts (existing)
  ├─ getAllBills(), getAllPeople(), getPersonById(),
  │   resolvePersonSlug(), billStatusTone()
  └─ unchanged

site/src/lib/analytics.ts (NEW)
  ├─ types: LegislatorStats, LeaderboardRow
  ├─ computeAllLegislatorStats() — single memoized pass over bills × people
  ├─ getLegislatorStats(slug) — lookup
  ├─ getLeaderboard({ metric, chamber? }) — sorted array
  └─ getComparison(slugs[]) — small wrapper for /compare

pages
  ├─ person/[id].astro      — add Stats panel above existing voting record
  ├─ scorecards.astro       — NEW. SSR sortable table, ?sort=&chamber= URL state
  └─ compare.astro          — NEW. SSR side-by-side, ?ids=A&ids=B URL state, <select> picker
```

The pattern mirrors `site/src/lib/heat.ts`: pure derivation module, memoized, consumed across pages.

## LegislatorStats shape

For each KY legislator (138):

| Field | Definition |
|---|---|
| `billsPrimarySponsored` | count of bills where `sponsors[].primary === true && person_id === me` |
| `billsCoSponsored` | count where `sponsors[].primary === false && person_id === me` |
| `votesCast` | count of `member_votes` entries with `person_id === me` (any option) |
| `votesParticipated` | subset where `option ∈ {"yes", "no"}` |
| `partyLoyaltyRate` | of `votesParticipated`, % matching majority of own-party choice on that vote |
| `effectivenessRate` | of `billsPrimarySponsored`, % whose `chamber_progress` shows passage past first chamber (uses `billStatusTone()`) |
| `lawRate` | of `billsPrimarySponsored`, % where `chamber_progress.governor === "signed"` or status is "law" |
| `topSubjects` | top 3 of `subjects[]` aggregated across primary + co-sponsored bills |
| `topCoSponsors` | top 3 person_ids most frequently appearing alongside me on `sponsors[]` (any role) |

**Small-N rule:** `partyLoyaltyRate` renders `—` when `votesParticipated < 20`; `effectivenessRate` and `lawRate` render `—` when `billsPrimarySponsored < 5`. Tooltip text: "not enough data". Counts always render.

**Null-safety:** member votes with `person_id: null` (legacy bill scrapes pre-`voter.id` capture) are excluded from per-person tallies but still counted in vote-level "majority of own party" denominators when the party can be inferred from the same vote's name+chamber lookup. Independents and `party === null` legislators get `—` for loyalty (no own-party majority defined).

## Page additions

**`/person/<slug>`** — 4-tile stats grid (Sponsored • Co-sponsored • Votes cast • Party loyalty) above the existing voting record. Below: chips for top 3 subjects, small list of top 3 co-sponsors as profile links. Effectiveness % shown only when `billsPrimarySponsored ≥ 5`. Council profiles unchanged.

**`/scorecards`** — sortable table; columns: Name, Party, District, Sponsored, Votes cast, Loyalty %, Effective %. Filter: chamber (`lower` / `upper` / all). Sort via `?sort=` URL param, server-rendered re-render on each request — no JS island. Default sort: bills sponsored desc. Add nav link in `Layout.astro` between People and Search. Caveat strip at top: "Based on the {SESSION} session. Loyalty hidden for legislators with <20 floor votes."

**`/compare`** — `?ids=ky-foo&ids=ky-bar` (1–3 ids). Side-by-side metric rows. Picker is a plain `<select multiple>` form that submits to URL. SSR. Linked from `/scorecards` ("Compare selected" action) and from each profile ("Compare" button next to the rep's name).

## Edge cases

- Bills with `person_id: null` everywhere (older scrapes) contribute zero loyalty data; sponsors with non-null IDs still count.
- "Independent" / null party → loyalty `—`.
- Bills crossing chambers counted under the primary sponsor regardless of chamber; effectiveness uses `chamber_progress` which captures cross-chamber passage.
- A vote with all members of one party voting `not voting` (e.g., quorum issue) yields no own-party majority for that vote and is dropped from loyalty denominators.

## Testing

- Vitest fixture-based suite for `analytics.ts` covering: primary-only sponsor, co-sponsor, mixed loyalty, null `person_id` votes, small-N suppression, top-subjects aggregation, top-co-sponsor tie-breaking.
- Build verification: `npm run build` (type-check + build), then preview at `/scorecards`, `/scorecards?chamber=upper&sort=loyalty`, `/compare?ids=ky-…&ids=ky-…`, and a sample `/person/<slug>`.

## File-level changes

| File | Change |
|---|---|
| `site/src/lib/analytics.ts` | **new** — derivation module |
| `site/src/pages/person/[id].astro` | render stats panel above voting record |
| `site/src/pages/scorecards.astro` | **new** |
| `site/src/pages/compare.astro` | **new** |
| `site/src/layouts/Layout.astro` | add `/scorecards` nav link |
| `site/src/styles/components.css` | stat-tile + leaderboard-table styles, reusing tokens |
| `site/package.json` | add `vitest` + `@vitest/ui` dev deps |
| `site/vitest.config.ts` | **new** |
| `site/src/lib/analytics.test.ts` | **new** |
