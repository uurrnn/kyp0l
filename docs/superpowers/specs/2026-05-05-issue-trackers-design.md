# Issue Trackers — Design Spec

**Date:** 2026-05-05
**Status:** Design approved, in implementation
**Repo:** [uurrnn/kyp0l](https://github.com/uurrnn/kyp0l) • Live site: https://uurrnn.github.io/kyp0l/

## Context

`/bills?subject=X` already filters bills by subject, but it's a flat list. A citizen wanting to understand where the legislature stands on education — what's hot, who's driving it, which committees own it — has to piece that together from `/bills`, `/scorecards`, and `/people`. This adds a curated topic landing page per featured subject (12 total), pulling bills + sponsors + committees into one digest.

Build-time derivation only. No new scrape, no new committed data. Reuses everything from `analytics.ts`, `heat.ts`, and `data.ts`.

## Scope

**In scope:**
- 12 per-topic pages under `/topic/<slug>`, one per `FEATURED_SUBJECTS` entry.
- Each page surfaces: hot bills (top 5 by `billHeat`), recent activity (last 10 bill actions), top sponsors (top 5 by primary-sponsorships), related committees (name match).
- A `/topics` index page listing all 12 with bill counts.
- Nav link "Topics" added between Bills and People.
- Dashboard subject-pulse chips re-pointed from `/bills?subject=X` to `/topic/<slug>` for the curated subjects.

**Out of scope:**
- Meeting integration on topic pages (agendas have no subject tags; would need text matching or LLM tagging).
- Per-topic vote breakdowns or "swing votes" analysis.
- Auto-derived subjects beyond the curated 12. Same convention as `featured-subjects.ts`.
- Procedural-tag topic pages (Technical Corrections etc.) — explicitly demoted in `featured-subjects.ts`.

## Architecture

```
data.ts (existing) ─── getBills, getBodies, getPeople, billStatusTone, ...
analytics.ts (existing) ─── computeAllLegislatorStats
heat.ts (existing) ─── billHeat
featured-subjects.ts (existing) ─── FEATURED_SUBJECTS

site/src/lib/topics.ts (NEW)
  ├─ slugifySubject(name) → URL-safe slug
  ├─ subjectFromSlug(slug) → subject name (or null)
  ├─ getAllTopics() → { subject, slug, count }[]
  └─ getTopicSummary(slug) →
      {
        subject, slug, totalBills, lastActionDate,
        hotBills: Bill[],            // top 5 by heat among this-subject bills
        recentActions: { bill, action }[],   // last 10 actions
        topSponsors: { person, count }[],    // top 5 primary-sponsorships
        relatedCommittees: Body[]    // committees whose name contains a topic keyword
      }

site/src/pages/topic/[slug].astro  — getStaticPaths over getAllTopics
site/src/pages/topics.astro         — index
site/src/layouts/Layout.astro       — nav link
site/src/pages/index.astro          — subject-pulse hrefs
site/src/styles/components.css      — small additions
```

## Slug rules

`slugifySubject("Education, Elementary And Secondary")` → `"education-elementary-and-secondary"`.

Pure kebab-case: lowercase, strip punctuation to spaces, collapse whitespace to `-`. Stable round-trip via `subjectFromSlug` (lookup in the curated list, not regenerated). Only the 12 featured subjects round-trip; everything else 404s on `/topic/`.

## Related committees

For each topic, match a committee body whose `name.toLowerCase()` contains the **first significant word** of the subject (excluding "and", "of", short words). Examples:
- "Education, Elementary And Secondary" → first word "education" → matches "House Standing Committee on Education", "Senate Standing Committee on Education", "Interim Joint Committee on Education".
- "Crimes And Punishments" → "crimes" → may match "Senate Standing Committee on Judiciary" if name contains "crime"; otherwise nothing.
- "Local Government" → "local" → matches "Local Government" committees.

Imperfect, but cheap and good enough for v1. Documented limitation: "Counties" and "Cities" mostly route into the Local Government cluster — accepted.

## Page sections

**`/topic/<slug>`:**
1. Header: H1 = subject name, subtitle with bill count + last activity date.
2. **Hot in this topic** — 5 cards, each: identifier, title, status badge, last action.
3. **Recent activity** — 10 rows, action description + date + bill identifier link.
4. **Top sponsors** — 5 rows, name (linked) + party chip + count.
5. **Related committees** — pill links to each `/body/<id>`.
6. CTA at bottom: "Browse all {N} bills →" → `/bills?subject=<encoded>`.

**`/topics`:**
- Title + intro.
- 12 cards in a grid, each linking to its `/topic/<slug>` with bill count + heat indicator.
- "Browse all subjects" link to `/bills` for the long tail.

## Testing

- `topics.test.ts` — fixture-based vitest:
  - `slugifySubject` round-trip for every featured subject
  - `getTopicSummary` aggregates bills, ranks sponsors correctly, picks committees by name match, returns empty arrays for an unknown subject
- Build verification: `/topics`, `/topic/education-elementary-and-secondary`, `/topic/<all 12>` render without errors.

## Out of scope (recap)

- Auto-derived subjects, LLM-tagged meetings, per-topic vote analytics, federal coverage. Same exclusions as the dashboard's subject pulse — the 12 curated subjects are the canonical issue set.
