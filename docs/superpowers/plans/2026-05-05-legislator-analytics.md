# Legislator Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-legislator computed metrics (sponsorship counts, party loyalty %, effectiveness %, top subjects, top co-sponsors) and surface them on three places: enriched `/person/<slug>` profile pages, a new `/scorecards` leaderboard, and a new `/compare` side-by-side view.

**Architecture:** Pure build-time derivation in a new `site/src/lib/analytics.ts` (mirrors the `heat.ts` pattern). One memoized pass over `getBills()` × `getPeople()` produces a `Map<personSlug, LegislatorStats>` consumed by all three pages. No new scrape, no new committed `data/*.json`, no new client-side island. SSR + URL-state forms throughout.

**Tech Stack:** TypeScript, Astro 5 (existing), Vitest (new dev dep for tests), reuses existing data accessors in `site/src/lib/data.ts`.

---

## File structure

| Path | Status | Responsibility |
|---|---|---|
| `site/src/lib/analytics.ts` | new | derivation module + public API |
| `site/src/lib/analytics.test.ts` | new | Vitest fixture suite |
| `site/vitest.config.ts` | new | minimal vitest config |
| `site/package.json` | modify | add vitest dev dep + `test` script |
| `site/src/pages/person/[id].astro` | modify | render stats grid above voting record |
| `site/src/pages/scorecards.astro` | new | SSR sortable leaderboard |
| `site/src/pages/compare.astro` | new | SSR side-by-side comparison |
| `site/src/layouts/Layout.astro` | modify | add `/scorecards` nav link |
| `site/src/styles/components.css` | modify | new styles for stat-tile-row, leaderboard, compare grid, caveat strip |

---

### Task 1: Set up Vitest and write a smoke test

**Files:**
- Create: `site/vitest.config.ts`
- Modify: `site/package.json`
- Create: `site/src/lib/analytics.test.ts` (placeholder for the next task)

- [ ] **Step 1: Add Vitest dev dep**

```bash
cd site && npm install --save-dev vitest@^2.1.0
```

Expected: `vitest` appears in `devDependencies` in `site/package.json`.

- [ ] **Step 2: Add a `test` script to `site/package.json`**

Add this line to the `scripts` block (after the `astro` line):

```json
    "test": "vitest run"
```

- [ ] **Step 3: Create `site/vitest.config.ts`**

```ts
import { defineConfig } from "vitest/config";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  resolve: {
    alias: {
      "~": path.join(here, "src"),
    },
  },
  test: {
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
});
```

- [ ] **Step 4: Create `site/src/lib/analytics.test.ts` with a smoke test**

```ts
import { describe, it, expect } from "vitest";

describe("smoke", () => {
  it("vitest is wired up", () => {
    expect(1 + 1).toBe(2);
  });
});
```

- [ ] **Step 5: Run the test**

```bash
cd site && npm test
```

Expected: 1 passing test.

- [ ] **Step 6: Commit**

```bash
git add site/package.json site/package-lock.json site/vitest.config.ts site/src/lib/analytics.test.ts
git commit -m "Add vitest scaffold for site-side TS tests"
```

---

### Task 2: Define `LegislatorStats` and implement count metrics

**Files:**
- Create: `site/src/lib/analytics.ts`
- Modify: `site/src/lib/analytics.test.ts`

These four counts are pure local sums per person; no cross-vote correlation.

- [ ] **Step 1: Write failing test for counts**

Replace the body of `site/src/lib/analytics.test.ts` with:

```ts
import { describe, it, expect } from "vitest";
import { computeStatsFromFixture, type FixtureBill, type FixturePerson } from "./analytics";

const ALICE: FixturePerson = { id: "ky-alice", chamber: "lower", party: "Democratic" };
const BOB: FixturePerson = { id: "ky-bob", chamber: "lower", party: "Republican" };

const ALICE_OCD = "ocd-person/alice";
const BOB_OCD = "ocd-person/bob";

const fixturePeopleIndex = new Map<string, string>([
  [ALICE_OCD, ALICE.id],
  [BOB_OCD, BOB.id],
]);

const bill1: FixtureBill = {
  id: "b1",
  subjects: ["Education"],
  chamber_progress: { lower: "passed", upper: null, governor: null },
  actions: [],
  current_status: "Passed House",
  sponsors: [
    { person_id: ALICE_OCD, party: "Democratic", primary: true },
    { person_id: BOB_OCD, party: "Republican", primary: false },
  ],
  votes: [
    {
      chamber: "lower",
      member_votes: [
        { person_id: ALICE_OCD, option: "yes" },
        { person_id: BOB_OCD, option: "no" },
      ],
    },
  ],
};

const bill2: FixtureBill = {
  id: "b2",
  subjects: ["Health"],
  chamber_progress: { lower: null, upper: null, governor: null },
  actions: [],
  current_status: "Introduced",
  sponsors: [
    { person_id: BOB_OCD, party: "Republican", primary: true },
    { person_id: ALICE_OCD, party: "Democratic", primary: false },
  ],
  votes: [],
};

describe("counts", () => {
  it("counts primary, co-sponsored, and votes per person", () => {
    const stats = computeStatsFromFixture([bill1, bill2], [ALICE, BOB], fixturePeopleIndex);
    const a = stats.get("ky-alice")!;
    const b = stats.get("ky-bob")!;

    expect(a.billsPrimarySponsored).toBe(1);
    expect(a.billsCoSponsored).toBe(1);
    expect(a.votesCast).toBe(1);
    expect(a.votesParticipated).toBe(1);

    expect(b.billsPrimarySponsored).toBe(1);
    expect(b.billsCoSponsored).toBe(1);
    expect(b.votesCast).toBe(1);
    expect(b.votesParticipated).toBe(1);
  });

  it("excludes member_votes with null person_id from per-person tallies", () => {
    const billWithNull: FixtureBill = {
      ...bill1,
      votes: [
        {
          chamber: "lower",
          member_votes: [
            { person_id: null, option: "yes" },
            { person_id: ALICE_OCD, option: "yes" },
          ],
        },
      ],
    };
    const stats = computeStatsFromFixture([billWithNull], [ALICE, BOB], fixturePeopleIndex);
    expect(stats.get("ky-alice")!.votesCast).toBe(1);
    // Bob has no member_vote here → 0 cast
    expect(stats.get("ky-bob")!.votesCast).toBe(0);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd site && npm test
```

Expected: FAIL with "Cannot find module './analytics'".

- [ ] **Step 3: Create `site/src/lib/analytics.ts` with types and the fixture entrypoint**

```ts
/**
 * Per-legislator analytics derived at build time from bills + people.
 * Pure functions; same inputs → same outputs. Mirrors heat.ts in shape.
 *
 * Public API:
 *   - getLegislatorStats(slug)        → LegislatorStats | undefined
 *   - getLeaderboard({ metric, chamber? }) → LeaderboardRow[]
 *   - getComparison(slugs)            → LegislatorStats[]
 *
 * Internals:
 *   - computeAllLegislatorStats()     → memoized; reads getBills() + getPeople()
 *   - computeStatsFromFixture(...)    → exported for tests; pure
 */

// ----- types

export interface LegislatorStats {
  personSlug: string;
  chamber: "lower" | "upper" | null;
  party: string | null;
  billsPrimarySponsored: number;
  billsCoSponsored: number;
  votesCast: number;
  votesParticipated: number;
  partyLoyaltyRate: number | null;        // null = small-N suppressed or no own-party majority
  effectivenessRate: number | null;       // null when billsPrimarySponsored < EFFECT_MIN_N
  lawRate: number | null;                 // null when billsPrimarySponsored < EFFECT_MIN_N
  topSubjects: string[];                  // up to 3
  topCoSponsors: { personId: string; count: number }[];  // up to 3
}

// Test-facing minimal shapes — narrower than the real Bill / Person.
export interface FixturePerson {
  id: string;
  chamber: "lower" | "upper" | null;
  party: string | null;
}

export interface FixtureSponsor {
  person_id: string | null;
  party: string | null;
  primary: boolean;
}

export interface FixtureMemberVote {
  person_id: string | null;
  option: string;
}

export interface FixtureVote {
  chamber: "lower" | "upper";
  member_votes: FixtureMemberVote[];
}

export interface FixtureBill {
  id: string;
  subjects: string[];
  chamber_progress: { lower: string | null; upper: string | null; governor: string | null };
  actions: { classification: string[] }[];
  current_status: string;
  sponsors: FixtureSponsor[];
  votes: FixtureVote[];
}

// ----- thresholds (exported so the UI can mention them in copy)

export const LOYALTY_MIN_N = 20;
export const EFFECT_MIN_N = 5;

// ----- core derivation

export function computeStatsFromFixture(
  bills: FixtureBill[],
  people: FixturePerson[],
  peopleIndex: Map<string, string>,
): Map<string, LegislatorStats> {
  const out = new Map<string, LegislatorStats>();
  for (const p of people) {
    out.set(p.id, {
      personSlug: p.id,
      chamber: p.chamber,
      party: p.party,
      billsPrimarySponsored: 0,
      billsCoSponsored: 0,
      votesCast: 0,
      votesParticipated: 0,
      partyLoyaltyRate: null,
      effectivenessRate: null,
      lawRate: null,
      topSubjects: [],
      topCoSponsors: [],
    });
  }

  // counts pass
  for (const bill of bills) {
    for (const s of bill.sponsors) {
      const slug = s.person_id ? peopleIndex.get(s.person_id) : undefined;
      if (!slug) continue;
      const row = out.get(slug);
      if (!row) continue;
      if (s.primary) row.billsPrimarySponsored++;
      else row.billsCoSponsored++;
    }
    for (const vote of bill.votes) {
      for (const mv of vote.member_votes) {
        const slug = mv.person_id ? peopleIndex.get(mv.person_id) : undefined;
        if (!slug) continue;
        const row = out.get(slug);
        if (!row) continue;
        row.votesCast++;
        if (mv.option === "yes" || mv.option === "no") row.votesParticipated++;
      }
    }
  }

  return out;
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd site && npm test
```

Expected: 2 passing tests.

- [ ] **Step 5: Commit**

```bash
git add site/src/lib/analytics.ts site/src/lib/analytics.test.ts
git commit -m "Add legislator-analytics scaffold with count metrics + fixture tests"
```

---

### Task 3: Compute `partyLoyaltyRate`

Loyalty for a vote = the legislator's choice (yes/no) matched the majority choice (yes/no) of own-party members on that same vote. Only votes where own party has a clear majority count toward both numerator and denominator. Independents and `party === null` always get `null`.

**Files:**
- Modify: `site/src/lib/analytics.ts`
- Modify: `site/src/lib/analytics.test.ts`

- [ ] **Step 1: Add tests**

Append to `site/src/lib/analytics.test.ts`:

```ts
describe("partyLoyaltyRate", () => {
  // Helper: build a slate of votes where Alice (D) and Bob (R) plus filler legislators vote.
  const FILLER: FixturePerson[] = Array.from({ length: 30 }, (_, i) => ({
    id: `ky-d-${i}`,
    chamber: "lower",
    party: "Democratic",
  }));
  const FILLER_INDEX = new Map<string, string>(FILLER.map((p) => [`ocd-person/d-${p.id.slice(5)}`, p.id]));

  function dvote(option: string, n: number): FixtureMemberVote[] {
    return Array.from({ length: n }, (_, i) => ({ person_id: `ocd-person/d-${i}`, option }));
  }

  it("rates Alice 100% loyal when she always votes with Democratic majority", () => {
    const idx = new Map([...fixturePeopleIndex, ...FILLER_INDEX]);
    const bills: FixtureBill[] = Array.from({ length: 25 }, (_, i) => ({
      id: `b${i}`,
      subjects: [],
      chamber_progress: { lower: null, upper: null, governor: null },
      actions: [],
      current_status: "",
      sponsors: [],
      votes: [
        {
          chamber: "lower",
          member_votes: [
            { person_id: ALICE_OCD, option: "yes" },
            ...dvote("yes", 20),  // 20 D voting yes → Dem majority is yes
            ...dvote("no", 5),    // 5 D voting no
          ],
        },
      ],
    }));

    const stats = computeStatsFromFixture(bills, [ALICE, BOB, ...FILLER], idx);
    expect(stats.get("ky-alice")!.partyLoyaltyRate).toBeCloseTo(1.0);
  });

  it("suppresses loyalty rate when votesParticipated < LOYALTY_MIN_N", () => {
    const idx = new Map([...fixturePeopleIndex, ...FILLER_INDEX]);
    const bills: FixtureBill[] = [
      {
        id: "b1",
        subjects: [],
        chamber_progress: { lower: null, upper: null, governor: null },
        actions: [],
        current_status: "",
        sponsors: [],
        votes: [
          {
            chamber: "lower",
            member_votes: [
              { person_id: ALICE_OCD, option: "yes" },
              ...dvote("yes", 20),
            ],
          },
        ],
      },
    ];
    const stats = computeStatsFromFixture(bills, [ALICE, BOB, ...FILLER], idx);
    expect(stats.get("ky-alice")!.partyLoyaltyRate).toBeNull();
  });

  it("returns null loyalty for legislators with no party", () => {
    const NEUTRAL: FixturePerson = { id: "ky-neutral", chamber: "lower", party: null };
    const NEUTRAL_OCD = "ocd-person/neutral";
    const idx = new Map([...fixturePeopleIndex, [NEUTRAL_OCD, NEUTRAL.id]]);
    const bills: FixtureBill[] = Array.from({ length: 25 }, (_, i) => ({
      id: `b${i}`,
      subjects: [],
      chamber_progress: { lower: null, upper: null, governor: null },
      actions: [],
      current_status: "",
      sponsors: [],
      votes: [{ chamber: "lower", member_votes: [{ person_id: NEUTRAL_OCD, option: "yes" }] }],
    }));
    const stats = computeStatsFromFixture(bills, [NEUTRAL], idx);
    expect(stats.get("ky-neutral")!.partyLoyaltyRate).toBeNull();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd site && npm test
```

Expected: 3 new failing tests (loyalty currently always `null` so the 100% test fails; small-N test passes incidentally; null-party test passes incidentally — only the 100% loyal test should fail at this point. Run anyway to confirm.)

- [ ] **Step 3: Implement loyalty computation**

In `site/src/lib/analytics.ts`, add this helper near the top:

```ts
function normalizeParty(p: string | null): "D" | "R" | "I" | null {
  if (!p) return null;
  const lower = p.toLowerCase();
  if (lower.startsWith("dem")) return "D";
  if (lower.startsWith("rep")) return "R";
  if (lower.startsWith("ind")) return "I";
  return null;
}
```

Then, inside `computeStatsFromFixture`, after the counts pass and before `return out`, add a loyalty pass:

```ts
  // loyalty pass: per vote, find each party's majority choice and compare
  // each member's choice against their own-party majority.
  // Track numerator (matched) + denominator (countable) per slug.
  const matched = new Map<string, number>();
  const denom = new Map<string, number>();

  // Build a slug → party lookup for inferring own-party majority.
  const slugParty = new Map<string, "D" | "R" | "I" | null>();
  for (const p of people) slugParty.set(p.id, normalizeParty(p.party));

  for (const bill of bills) {
    for (const vote of bill.votes) {
      // tally party-by-party choice on this vote
      const tally: Record<"D" | "R", { yes: number; no: number }> = {
        D: { yes: 0, no: 0 },
        R: { yes: 0, no: 0 },
      };
      for (const mv of vote.member_votes) {
        const slug = mv.person_id ? peopleIndex.get(mv.person_id) : undefined;
        if (!slug) continue;
        const party = slugParty.get(slug);
        if (party !== "D" && party !== "R") continue;
        if (mv.option === "yes") tally[party].yes++;
        else if (mv.option === "no") tally[party].no++;
      }

      const majority: Partial<Record<"D" | "R", "yes" | "no">> = {};
      for (const k of ["D", "R"] as const) {
        const t = tally[k];
        if (t.yes > t.no) majority[k] = "yes";
        else if (t.no > t.yes) majority[k] = "no";
        // tie or all-abstain → no majority for that party on this vote
      }

      for (const mv of vote.member_votes) {
        const slug = mv.person_id ? peopleIndex.get(mv.person_id) : undefined;
        if (!slug) continue;
        if (mv.option !== "yes" && mv.option !== "no") continue;
        const party = slugParty.get(slug);
        if (party !== "D" && party !== "R") continue;
        const maj = majority[party];
        if (!maj) continue;
        denom.set(slug, (denom.get(slug) ?? 0) + 1);
        if (mv.option === maj) matched.set(slug, (matched.get(slug) ?? 0) + 1);
      }
    }
  }

  for (const row of out.values()) {
    const d = denom.get(row.personSlug) ?? 0;
    if (d < LOYALTY_MIN_N) continue;
    const m = matched.get(row.personSlug) ?? 0;
    row.partyLoyaltyRate = m / d;
  }
```

- [ ] **Step 4: Run tests**

```bash
cd site && npm test
```

Expected: all loyalty tests pass.

- [ ] **Step 5: Commit**

```bash
git add site/src/lib/analytics.ts site/src/lib/analytics.test.ts
git commit -m "Compute legislator party loyalty rate with small-N suppression"
```

---

### Task 4: Compute `effectivenessRate` and `lawRate`

Effectiveness = % of bills you primary-sponsored that progressed past first chamber. Law = % that became law. Both suppressed when `billsPrimarySponsored < EFFECT_MIN_N`. We mirror `billStatusTone()` semantics from `data.ts`.

**Files:**
- Modify: `site/src/lib/analytics.ts`
- Modify: `site/src/lib/analytics.test.ts`

- [ ] **Step 1: Add tests**

Append to `site/src/lib/analytics.test.ts`:

```ts
describe("effectiveness and law rates", () => {
  function makeBill(id: string, primarySponsor: string, progress: FixtureBill["chamber_progress"], actions: { classification: string[] }[] = []): FixtureBill {
    return {
      id,
      subjects: [],
      chamber_progress: progress,
      actions,
      current_status: "",
      sponsors: [{ person_id: primarySponsor, party: "Democratic", primary: true }],
      votes: [],
    };
  }

  it("effectiveness counts bills past first chamber", () => {
    const idx = new Map(fixturePeopleIndex);
    const bills: FixtureBill[] = [
      // 5 sponsored by Alice. 3 cross to second chamber, 1 became law, 1 stuck in committee.
      makeBill("b1", ALICE_OCD, { lower: "passed", upper: null, governor: null }),
      makeBill("b2", ALICE_OCD, { lower: "passed", upper: null, governor: null }),
      makeBill("b3", ALICE_OCD, { lower: "passed", upper: "introduced", governor: null }),
      makeBill("b4", ALICE_OCD, { lower: "passed", upper: "passed", governor: "signed" }),
      makeBill("b5", ALICE_OCD, { lower: "in_committee", upper: null, governor: null }),
    ];
    const stats = computeStatsFromFixture(bills, [ALICE, BOB], idx);
    // 4 of 5 are past first chamber (b1, b2, b3, b4)
    expect(stats.get("ky-alice")!.effectivenessRate).toBeCloseTo(4 / 5);
    // 1 of 5 became law
    expect(stats.get("ky-alice")!.lawRate).toBeCloseTo(1 / 5);
  });

  it("suppresses both rates when billsPrimarySponsored < EFFECT_MIN_N", () => {
    const idx = new Map(fixturePeopleIndex);
    const bills: FixtureBill[] = [
      makeBill("b1", ALICE_OCD, { lower: "passed", upper: null, governor: null }),
    ];
    const stats = computeStatsFromFixture(bills, [ALICE, BOB], idx);
    expect(stats.get("ky-alice")!.effectivenessRate).toBeNull();
    expect(stats.get("ky-alice")!.lawRate).toBeNull();
  });

  it("treats became-law action as law even without governor=signed", () => {
    const idx = new Map(fixturePeopleIndex);
    const bills: FixtureBill[] = Array.from({ length: 5 }, (_, i) =>
      makeBill(
        `b${i}`,
        ALICE_OCD,
        { lower: "passed", upper: "passed", governor: null },
        [{ classification: ["became-law"] }],
      ),
    );
    const stats = computeStatsFromFixture(bills, [ALICE, BOB], idx);
    expect(stats.get("ky-alice")!.lawRate).toBeCloseTo(1.0);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd site && npm test
```

Expected: 3 new failing tests.

- [ ] **Step 3: Implement effectiveness + law**

In `site/src/lib/analytics.ts`, add helpers near the top:

```ts
function pastFirstChamber(progress: FixtureBill["chamber_progress"]): boolean {
  // "Past first chamber" = either the originating chamber passed and the other received it,
  // or both passed, or it became law (covered by both passed).
  const { lower, upper, governor } = progress;
  if (governor === "signed") return true;
  if (lower === "passed" && upper) return true;       // crossed over
  if (upper === "passed" && lower) return true;
  if (lower === "passed" && upper === "passed") return true;
  // single-chamber pass without the other receiving doesn't count yet
  return false;
}

function becameLaw(bill: FixtureBill): boolean {
  if (bill.chamber_progress.governor === "signed") return true;
  for (const a of bill.actions) {
    if (a.classification.includes("became-law")) return true;
    if (a.classification.includes("veto-override-passage")) return true;
  }
  return false;
}
```

Then, in `computeStatsFromFixture` after the loyalty pass, add an effectiveness pass:

```ts
  // effectiveness pass: aggregate per primary sponsor
  const primaryBills = new Map<string, FixtureBill[]>();
  for (const bill of bills) {
    for (const s of bill.sponsors) {
      if (!s.primary) continue;
      const slug = s.person_id ? peopleIndex.get(s.person_id) : undefined;
      if (!slug) continue;
      const arr = primaryBills.get(slug) ?? [];
      arr.push(bill);
      primaryBills.set(slug, arr);
    }
  }
  for (const [slug, theirBills] of primaryBills) {
    const row = out.get(slug);
    if (!row || theirBills.length < EFFECT_MIN_N) continue;
    const effective = theirBills.filter((b) => pastFirstChamber(b.chamber_progress)).length;
    const lawed = theirBills.filter(becameLaw).length;
    row.effectivenessRate = effective / theirBills.length;
    row.lawRate = lawed / theirBills.length;
  }
```

- [ ] **Step 4: Run tests**

```bash
cd site && npm test
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add site/src/lib/analytics.ts site/src/lib/analytics.test.ts
git commit -m "Compute effectiveness and law rates for primary-sponsored bills"
```

---

### Task 5: Compute `topSubjects` and `topCoSponsors`

Subjects: top 3 by frequency across all bills the person appeared on (any role). Co-sponsors: top 3 person_ids most frequently appearing alongside the person on `sponsors[]`. Ties broken by alphabetical order on the key.

**Files:**
- Modify: `site/src/lib/analytics.ts`
- Modify: `site/src/lib/analytics.test.ts`

- [ ] **Step 1: Add tests**

Append to `site/src/lib/analytics.test.ts`:

```ts
describe("topSubjects and topCoSponsors", () => {
  it("ranks subjects by frequency across primary + co-sponsored bills", () => {
    const idx = new Map(fixturePeopleIndex);
    const bills: FixtureBill[] = [
      { id: "b1", subjects: ["Education", "Health"], chamber_progress: { lower: null, upper: null, governor: null }, actions: [], current_status: "", sponsors: [{ person_id: ALICE_OCD, party: "D", primary: true }], votes: [] },
      { id: "b2", subjects: ["Education"], chamber_progress: { lower: null, upper: null, governor: null }, actions: [], current_status: "", sponsors: [{ person_id: ALICE_OCD, party: "D", primary: false }], votes: [] },
      { id: "b3", subjects: ["Health", "Tax"], chamber_progress: { lower: null, upper: null, governor: null }, actions: [], current_status: "", sponsors: [{ person_id: ALICE_OCD, party: "D", primary: true }], votes: [] },
    ];
    const stats = computeStatsFromFixture(bills, [ALICE, BOB], idx);
    // Education: 2, Health: 2, Tax: 1 → ties broken alphabetically
    expect(stats.get("ky-alice")!.topSubjects).toEqual(["Education", "Health", "Tax"]);
  });

  it("ranks co-sponsors by frequency, excluding self", () => {
    const idx = new Map(fixturePeopleIndex);
    const bills: FixtureBill[] = [
      { id: "b1", subjects: [], chamber_progress: { lower: null, upper: null, governor: null }, actions: [], current_status: "", sponsors: [
        { person_id: ALICE_OCD, party: "D", primary: true },
        { person_id: BOB_OCD, party: "R", primary: false },
      ], votes: [] },
      { id: "b2", subjects: [], chamber_progress: { lower: null, upper: null, governor: null }, actions: [], current_status: "", sponsors: [
        { person_id: ALICE_OCD, party: "D", primary: false },
        { person_id: BOB_OCD, party: "R", primary: true },
      ], votes: [] },
    ];
    const stats = computeStatsFromFixture(bills, [ALICE, BOB], idx);
    expect(stats.get("ky-alice")!.topCoSponsors).toEqual([{ personId: BOB_OCD, count: 2 }]);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd site && npm test
```

Expected: 2 new failing tests.

- [ ] **Step 3: Implement subjects + co-sponsors**

In `site/src/lib/analytics.ts`, add a helper near the top:

```ts
function topN<K>(counts: Map<K, number>, n: number, tieBreaker: (a: K, b: K) => number): { key: K; count: number }[] {
  const entries = Array.from(counts.entries()).map(([key, count]) => ({ key, count }));
  entries.sort((a, b) => (b.count - a.count) || tieBreaker(a.key, b.key));
  return entries.slice(0, n);
}
```

Then, inside `computeStatsFromFixture` after the effectiveness pass, add aggregation for subjects and co-sponsors:

```ts
  // subjects + co-sponsors
  const subjectCounts = new Map<string, Map<string, number>>();   // slug → subject → count
  const coCounts = new Map<string, Map<string, number>>();        // slug → other_person_id → count
  for (const bill of bills) {
    const billSlugs = new Set<string>();
    for (const s of bill.sponsors) {
      const slug = s.person_id ? peopleIndex.get(s.person_id) : undefined;
      if (slug) billSlugs.add(slug);
    }
    for (const slug of billSlugs) {
      let sm = subjectCounts.get(slug);
      if (!sm) { sm = new Map(); subjectCounts.set(slug, sm); }
      for (const subj of bill.subjects) sm.set(subj, (sm.get(subj) ?? 0) + 1);

      let cm = coCounts.get(slug);
      if (!cm) { cm = new Map(); coCounts.set(slug, cm); }
      for (const s of bill.sponsors) {
        const otherSlug = s.person_id ? peopleIndex.get(s.person_id) : undefined;
        if (!otherSlug || otherSlug === slug || !s.person_id) continue;
        cm.set(s.person_id, (cm.get(s.person_id) ?? 0) + 1);
      }
    }
  }
  for (const row of out.values()) {
    const sm = subjectCounts.get(row.personSlug);
    if (sm) {
      row.topSubjects = topN(sm, 3, (a, b) => a.localeCompare(b)).map((e) => e.key);
    }
    const cm = coCounts.get(row.personSlug);
    if (cm) {
      row.topCoSponsors = topN(cm, 3, (a, b) => a.localeCompare(b)).map((e) => ({ personId: e.key, count: e.count }));
    }
  }
```

- [ ] **Step 4: Run tests**

```bash
cd site && npm test
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add site/src/lib/analytics.ts site/src/lib/analytics.test.ts
git commit -m "Compute top subjects and top co-sponsors per legislator"
```

---

### Task 6: Wire to real data + public API

Add the memoized real-data entrypoint and the three accessors used by pages.

**Files:**
- Modify: `site/src/lib/analytics.ts`

- [ ] **Step 1: Append the public API to `site/src/lib/analytics.ts`**

Add at the bottom of the file:

```ts
// ----- public API: real data path

import { getBills, getPeople } from "./data";

let _allStats: Map<string, LegislatorStats> | null = null;

export function computeAllLegislatorStats(): Map<string, LegislatorStats> {
  if (_allStats) return _allStats;

  const bills = getBills();
  const people = getPeople().filter((p) => p.source === "openstates");

  // Real data uses the same shape as our fixtures, just wider — narrow it for the pure fn.
  const idx = new Map<string, string>();
  for (const p of getPeople()) idx.set(p.source_id, p.id);

  const fixturePeople: FixturePerson[] = people.map((p) => ({
    id: p.id,
    chamber: p.chamber,
    party: p.party,
  }));

  const fixtureBills: FixtureBill[] = bills.map((b) => ({
    id: b.id,
    subjects: b.subjects,
    chamber_progress: b.chamber_progress,
    actions: b.actions.map((a) => ({ classification: a.classification })),
    current_status: b.current_status,
    sponsors: b.sponsors.map((s) => ({ person_id: s.person_id ?? null, party: s.party, primary: s.primary })),
    votes: b.votes.map((v) => ({
      chamber: v.chamber,
      member_votes: v.member_votes.map((mv) => ({ person_id: mv.person_id ?? null, option: mv.option })),
    })),
  }));

  _allStats = computeStatsFromFixture(fixtureBills, fixturePeople, idx);
  return _allStats;
}

export function getLegislatorStats(slug: string): LegislatorStats | undefined {
  return computeAllLegislatorStats().get(slug);
}

export type LeaderboardMetric =
  | "billsPrimarySponsored"
  | "votesCast"
  | "partyLoyaltyRate"
  | "effectivenessRate";

export interface LeaderboardOptions {
  metric: LeaderboardMetric;
  chamber?: "lower" | "upper" | null;
}

export function getLeaderboard(opts: LeaderboardOptions): LegislatorStats[] {
  const all = Array.from(computeAllLegislatorStats().values());
  const filtered = opts.chamber
    ? all.filter((s) => s.chamber === opts.chamber)
    : all;
  const key = opts.metric;
  return [...filtered].sort((a, b) => {
    const av = a[key];
    const bv = b[key];
    // Treat null as -Infinity so suppressed rows sink to the bottom.
    const an = av == null ? -Infinity : (av as number);
    const bn = bv == null ? -Infinity : (bv as number);
    if (bn !== an) return bn - an;
    return a.personSlug.localeCompare(b.personSlug);
  });
}

export function getComparison(slugs: string[]): LegislatorStats[] {
  const all = computeAllLegislatorStats();
  const out: LegislatorStats[] = [];
  for (const slug of slugs) {
    const s = all.get(slug);
    if (s) out.push(s);
  }
  return out;
}
```

- [ ] **Step 2: Run tests to verify nothing broke**

```bash
cd site && npm test
```

Expected: all 10+ tests still pass.

- [ ] **Step 3: Smoke-build to confirm typings load real data without runtime errors**

```bash
cd site && npm run build 2>&1 | tail -30
```

Expected: build completes (sites pages aren't using analytics yet, so this is a pure type/import check).

- [ ] **Step 4: Commit**

```bash
git add site/src/lib/analytics.ts
git commit -m "Add public API for legislator analytics (memoized, real-data path)"
```

---

### Task 7: Enrich `/person/<slug>` with the stats panel

Renders only for `person.source === "openstates"`. Slots in above the existing "Bills sponsored" section.

**Files:**
- Modify: `site/src/pages/person/[id].astro`
- Modify: `site/src/styles/components.css`

- [ ] **Step 1: Add styles for the stats grid**

Append to `site/src/styles/components.css`:

```css
/* legislator stats grid (profile + compare pages) ------------------------- */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}
@media (max-width: 600px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
}
.stat-grid .tile-num.muted { color: var(--fg-mute2); }
.stat-grid .tile-num small {
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  font-weight: 400;
  color: var(--fg-muted);
  margin-left: 4px;
}

.subject-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin: var(--space-2) 0 var(--space-5);
}
.subject-chip {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: var(--text-xs);
  background: var(--bg-subtle);
  color: var(--fg);
  border: 1px solid var(--border);
  text-decoration: none;
}
.subject-chip:hover { border-color: var(--accent); color: var(--accent); }

.cosponsor-list {
  list-style: none;
  padding: 0;
  margin: 0 0 var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.cosponsor-list li { font-size: var(--text-sm); }
.cosponsor-list .count {
  font-variant-numeric: tabular-nums;
  color: var(--fg-muted);
  font-size: var(--text-xs);
  margin-left: var(--space-2);
}

.compare-cta {
  display: inline-block;
  margin-left: var(--space-3);
  padding: 2px 10px;
  font-size: var(--text-xs);
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--fg-muted);
  text-decoration: none;
}
.compare-cta:hover { border-color: var(--accent); color: var(--accent); }
```

- [ ] **Step 2: Add stats panel to the profile page**

In `site/src/pages/person/[id].astro`, edit the imports block (around line 12) to add analytics:

Replace:

```astro
import {
  getPeople,
  getPersonById,
  getBodyById,
  getBillsSponsoredBy,
  getMemberVotesByPerson,
  getCommitteesForPerson,
  billStatusTone,
  partyAbbrev,
} from "~/lib/data";
```

with:

```astro
import {
  getPeople,
  getPersonById,
  getBodyById,
  getBillsSponsoredBy,
  getMemberVotesByPerson,
  getCommitteesForPerson,
  billStatusTone,
  partyAbbrev,
  resolvePersonSlug,
  getPersonByOcdId,
} from "~/lib/data";
import { getLegislatorStats } from "~/lib/analytics";
```

Then in the frontmatter (after the `committees = ...` line, around line 28), add:

```astro
const stats = person && person.source === "openstates"
  ? getLegislatorStats(person.id)
  : undefined;
function pct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${Math.round(v * 100)}%`;
}
```

Then in the template, immediately after the `</header>` of `.person-header` and before `<div class="bill-layout">`, add:

```astro
      {stats && person.source === "openstates" && (
        <>
          <div class="stat-grid">
            <div class="tile">
              <div class="tile-num">{stats.billsPrimarySponsored}</div>
              <div class="tile-label">Bills sponsored</div>
            </div>
            <div class="tile">
              <div class="tile-num">{stats.billsCoSponsored}</div>
              <div class="tile-label">Bills co-sponsored</div>
            </div>
            <div class="tile">
              <div class="tile-num">{stats.votesCast}</div>
              <div class="tile-label">Floor votes cast</div>
            </div>
            <div class="tile">
              <div class={`tile-num ${stats.partyLoyaltyRate == null ? "muted" : ""}`} title={stats.partyLoyaltyRate == null ? "Not enough floor votes to compute" : undefined}>
                {pct(stats.partyLoyaltyRate)}
              </div>
              <div class="tile-label">Party loyalty</div>
            </div>
          </div>

          {stats.effectivenessRate != null && (
            <p class="meta-line" style="margin-bottom: var(--space-5);">
              <strong>{pct(stats.effectivenessRate)}</strong> of their {stats.billsPrimarySponsored} primary-sponsored bills passed at least one chamber.
              {stats.lawRate != null && stats.lawRate > 0 && (
                <> <strong>{pct(stats.lawRate)}</strong> became law.</>
              )}
            </p>
          )}

          {stats.topSubjects.length > 0 && (
            <>
              <h3 style="margin-top: 0;">Focuses on</h3>
              <div class="subject-chips">
                {stats.topSubjects.map((s) => (
                  <a class="subject-chip" href={`${base}bills?subject=${encodeURIComponent(s)}`}>{s}</a>
                ))}
              </div>
            </>
          )}

          {stats.topCoSponsors.length > 0 && (
            <>
              <h3 style="margin-top: 0;">Frequent co-sponsors</h3>
              <ul class="cosponsor-list">
                {stats.topCoSponsors.map((c) => {
                  const co = getPersonByOcdId(c.personId);
                  if (!co) return null;
                  return (
                    <li>
                      <a href={`${base}person/${co.id}`}>{co.name}</a>
                      <span class="count">{c.count} bill{c.count === 1 ? "" : "s"} together</span>
                    </li>
                  );
                })}
              </ul>
            </>
          )}

          <p style="margin-bottom: var(--space-5);">
            <a class="compare-cta" href={`${base}compare?ids=${person.id}`}>Compare with peers →</a>
          </p>
        </>
      )}
```

- [ ] **Step 3: Build and visually smoke-check**

```bash
cd site && npm run build
```

Expected: build succeeds. (Visual check happens in the verification phase.)

- [ ] **Step 4: Commit**

```bash
git add site/src/pages/person/[id].astro site/src/styles/components.css
git commit -m "Render legislator stats grid + focuses + co-sponsors on profile pages"
```

---

### Task 8: Build `/scorecards` leaderboard page

SSR. Sortable via `?sort=` URL param, filterable via `?chamber=`. No JS island.

**Files:**
- Create: `site/src/pages/scorecards.astro`
- Modify: `site/src/styles/components.css`

- [ ] **Step 1: Add table styles**

Append to `site/src/styles/components.css`:

```css
/* scorecards table -------------------------------------------------------- */
.scorecards-controls {
  display: flex;
  gap: var(--space-3);
  align-items: baseline;
  margin-bottom: var(--space-3);
  font-size: var(--text-sm);
  color: var(--fg-muted);
  flex-wrap: wrap;
}
.scorecards-controls a {
  color: var(--fg-muted);
  text-decoration: none;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid transparent;
}
.scorecards-controls a.active {
  color: var(--fg);
  border-color: var(--border-strong);
  background: var(--bg-card);
}
.scorecards-caveat {
  font-size: var(--text-sm);
  color: var(--fg-muted);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--space-2) var(--space-3);
  margin-bottom: var(--space-4);
}

.scorecards-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.scorecards-table th, .scorecards-table td {
  padding: var(--space-2) var(--space-3);
  text-align: left;
  border-bottom: 1px solid var(--border);
  vertical-align: baseline;
}
.scorecards-table tbody tr:last-child td { border-bottom: 0; }
.scorecards-table th { font-weight: 600; color: var(--fg-muted); background: var(--bg-subtle); }
.scorecards-table th a { color: var(--fg-muted); text-decoration: none; }
.scorecards-table th a:hover { color: var(--accent); }
.scorecards-table th a.active { color: var(--fg); }
.scorecards-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
.scorecards-table td.muted { color: var(--fg-mute2); }
```

- [ ] **Step 2: Create the page**

Create `site/src/pages/scorecards.astro`:

```astro
---
import Layout from "~/layouts/Layout.astro";
import { getPeople, partyAbbrev, getSessionStatus } from "~/lib/data";
import { getLeaderboard, type LeaderboardMetric } from "~/lib/analytics";

const base = import.meta.env.BASE_URL;

const url = Astro.url;
const sort = (url.searchParams.get("sort") ?? "billsPrimarySponsored") as LeaderboardMetric;
const chamberParam = url.searchParams.get("chamber");
const chamber: "lower" | "upper" | null = chamberParam === "lower" || chamberParam === "upper" ? chamberParam : null;

const valid: LeaderboardMetric[] = ["billsPrimarySponsored", "votesCast", "partyLoyaltyRate", "effectivenessRate"];
const metric: LeaderboardMetric = (valid as string[]).includes(sort) ? sort : "billsPrimarySponsored";

const rows = getLeaderboard({ metric, chamber });

const peopleById = new Map(getPeople().map((p) => [p.id, p]));
const session = getSessionStatus().session ?? "current";

function pct(v: number | null): string {
  if (v == null) return "—";
  return `${Math.round(v * 100)}%`;
}
function partyClass(party: string | null): string {
  if (!party) return "";
  const p = party.toLowerCase();
  if (p.startsWith("dem")) return "party-d";
  if (p.startsWith("rep")) return "party-r";
  return "party-i";
}
function sortHref(s: LeaderboardMetric): string {
  const u = new URLSearchParams(url.searchParams);
  u.set("sort", s);
  return `${base}scorecards?${u.toString()}`;
}
function chamberHref(c: "lower" | "upper" | null): string {
  const u = new URLSearchParams(url.searchParams);
  if (c) u.set("chamber", c); else u.delete("chamber");
  return `${base}scorecards?${u.toString()}`;
}
---

<Layout title="Scorecards — kyp0l" description="How Kentucky legislators stack up on activity, party loyalty, and effectiveness for the current session.">
  <h1>Legislator scorecards</h1>
  <p class="scorecards-caveat">
    Based on the <strong>{session}</strong> session. Loyalty hidden for legislators with fewer than 20 floor votes; effectiveness hidden for fewer than 5 sponsored bills. Metro Council is excluded — no roll-call data available.
  </p>

  <div class="scorecards-controls">
    <span>Chamber:</span>
    <a href={chamberHref(null)} class={chamber == null ? "active" : ""}>All</a>
    <a href={chamberHref("upper")} class={chamber === "upper" ? "active" : ""}>Senate</a>
    <a href={chamberHref("lower")} class={chamber === "lower" ? "active" : ""}>House</a>
  </div>

  <table class="scorecards-table">
    <thead>
      <tr>
        <th>Name</th>
        <th>Party</th>
        <th>District</th>
        <th class="num"><a href={sortHref("billsPrimarySponsored")} class={metric === "billsPrimarySponsored" ? "active" : ""}>Sponsored</a></th>
        <th class="num"><a href={sortHref("votesCast")} class={metric === "votesCast" ? "active" : ""}>Votes</a></th>
        <th class="num"><a href={sortHref("partyLoyaltyRate")} class={metric === "partyLoyaltyRate" ? "active" : ""}>Loyalty</a></th>
        <th class="num"><a href={sortHref("effectivenessRate")} class={metric === "effectivenessRate" ? "active" : ""}>Effective</a></th>
      </tr>
    </thead>
    <tbody>
      {rows.map((r) => {
        const p = peopleById.get(r.personSlug);
        if (!p) return null;
        return (
          <tr>
            <td><a href={`${base}person/${r.personSlug}`}>{p.name}</a></td>
            <td>{p.party && <span class={`party-chip ${partyClass(p.party)}`}>{partyAbbrev(p.party)}</span>}</td>
            <td>{p.district ? `D${p.district}` : "—"}</td>
            <td class="num">{r.billsPrimarySponsored}</td>
            <td class="num">{r.votesCast}</td>
            <td class={r.partyLoyaltyRate == null ? "num muted" : "num"}>{pct(r.partyLoyaltyRate)}</td>
            <td class={r.effectivenessRate == null ? "num muted" : "num"}>{pct(r.effectivenessRate)}</td>
          </tr>
        );
      })}
    </tbody>
  </table>
</Layout>
```

- [ ] **Step 3: Build**

```bash
cd site && npm run build
```

Expected: build succeeds; `dist/scorecards/index.html` is produced.

- [ ] **Step 4: Commit**

```bash
git add site/src/pages/scorecards.astro site/src/styles/components.css
git commit -m "Add /scorecards leaderboard with chamber filter and column sort"
```

---

### Task 9: Build `/compare` side-by-side page

`?ids=A&ids=B&ids=C` (1–3 ids). SSR. Picker is a plain `<select multiple>` form.

**Files:**
- Create: `site/src/pages/compare.astro`
- Modify: `site/src/styles/components.css`

- [ ] **Step 1: Add compare-grid styles**

Append to `site/src/styles/components.css`:

```css
/* compare grid ------------------------------------------------------------ */
.compare-grid {
  display: grid;
  grid-template-columns: 200px repeat(var(--compare-cols, 1), 1fr);
  gap: 0;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  margin-bottom: var(--space-5);
}
.compare-grid > div {
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border);
}
.compare-grid .row-label {
  font-size: var(--text-xs);
  color: var(--fg-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  background: var(--bg-subtle);
}
.compare-grid .person-head {
  font-family: var(--font-serif);
  font-size: var(--text-base);
  font-weight: 600;
  background: var(--bg-subtle);
}
.compare-grid .num {
  font-variant-numeric: tabular-nums;
  font-size: var(--text-base);
}
.compare-grid .muted { color: var(--fg-mute2); }

.compare-picker {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--space-4);
  margin-bottom: var(--space-5);
}
.compare-picker select {
  font-family: inherit;
  font-size: var(--text-sm);
  width: 100%;
  min-height: 200px;
  padding: var(--space-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
  color: var(--fg);
}
.compare-picker button {
  margin-top: var(--space-3);
  padding: 6px 16px;
  background: var(--accent);
  color: white;
  border: 0;
  border-radius: var(--radius);
  font-size: var(--text-sm);
  cursor: pointer;
}
.compare-picker button:hover { opacity: 0.9; }
.compare-picker .hint { font-size: var(--text-xs); color: var(--fg-muted); margin-top: var(--space-2); }
```

- [ ] **Step 2: Create the page**

Create `site/src/pages/compare.astro`:

```astro
---
import Layout from "~/layouts/Layout.astro";
import { getPeople, getPersonById, partyAbbrev } from "~/lib/data";
import { getComparison } from "~/lib/analytics";

const base = import.meta.env.BASE_URL;
const url = Astro.url;

const ids = url.searchParams.getAll("ids").slice(0, 3);
const stats = getComparison(ids);
const people = stats
  .map((s) => getPersonById(s.personSlug))
  .filter((p): p is NonNullable<typeof p> => !!p);

const allLegislators = getPeople()
  .filter((p) => p.source === "openstates")
  .sort((a, b) => a.name.localeCompare(b.name));

function pct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${Math.round(v * 100)}%`;
}
function partyClass(party: string | null): string {
  if (!party) return "";
  const p = party.toLowerCase();
  if (p.startsWith("dem")) return "party-d";
  if (p.startsWith("rep")) return "party-r";
  return "party-i";
}
---

<Layout title="Compare legislators — kyp0l" description="Pick up to three Kentucky legislators and see their metrics side-by-side.">
  <h1>Compare legislators</h1>

  {stats.length === 0 ? (
    <p style="color: var(--fg-muted); margin-bottom: var(--space-4);">
      Pick up to three legislators below.
    </p>
  ) : (
    <div class="compare-grid" style={`--compare-cols: ${stats.length};`}>
      <div class="row-label">&nbsp;</div>
      {people.map((p) => (
        <div class="person-head">
          <a href={`${base}person/${p.id}`} style="color: inherit; text-decoration: none;">{p.name}</a>
          <div style="font-size: var(--text-xs); font-weight: 400; color: var(--fg-muted); margin-top: 2px;">
            {p.party && <span class={`party-chip ${partyClass(p.party)}`}>{partyAbbrev(p.party)}</span>}
            {p.district && <span style="margin-left: var(--space-2);">D{p.district}</span>}
          </div>
        </div>
      ))}

      <div class="row-label">Sponsored</div>
      {stats.map((s) => <div class="num">{s.billsPrimarySponsored}</div>)}

      <div class="row-label">Co-sponsored</div>
      {stats.map((s) => <div class="num">{s.billsCoSponsored}</div>)}

      <div class="row-label">Floor votes</div>
      {stats.map((s) => <div class="num">{s.votesCast}</div>)}

      <div class="row-label">Party loyalty</div>
      {stats.map((s) => <div class={s.partyLoyaltyRate == null ? "num muted" : "num"}>{pct(s.partyLoyaltyRate)}</div>)}

      <div class="row-label">Effective</div>
      {stats.map((s) => <div class={s.effectivenessRate == null ? "num muted" : "num"}>{pct(s.effectivenessRate)}</div>)}

      <div class="row-label">Top subject</div>
      {stats.map((s) => <div>{s.topSubjects[0] ?? <span class="muted">—</span>}</div>)}
    </div>
  )}

  <form class="compare-picker" method="get" action={`${base}compare`}>
    <h3 style="margin-top: 0;">Pick legislators (Ctrl/Cmd-click for multiple, up to 3)</h3>
    <select name="ids" multiple>
      {allLegislators.map((p) => (
        <option value={p.id} selected={ids.includes(p.id)}>
          {p.name} — {partyAbbrev(p.party)} {p.district ? `D${p.district}` : ""}
        </option>
      ))}
    </select>
    <button type="submit">Compare</button>
    <p class="hint">Only the first three selections are used.</p>
  </form>
</Layout>
```

- [ ] **Step 3: Build**

```bash
cd site && npm run build
```

Expected: build succeeds; `dist/compare/index.html` is produced.

- [ ] **Step 4: Commit**

```bash
git add site/src/pages/compare.astro site/src/styles/components.css
git commit -m "Add /compare side-by-side legislator view with form picker"
```

---

### Task 10: Add nav link

**Files:**
- Modify: `site/src/layouts/Layout.astro`

- [ ] **Step 1: Add the link**

In `site/src/layouts/Layout.astro`, find the `<nav class="site-nav">` block (around line 35) and add the Scorecards link between People and Search:

Replace:

```astro
          <a href={`${base}people`} class={isActive(`${base}people`) ? "active" : ""}>People</a>
          <a href={`${base}search`} class={isActive(`${base}search`) ? "active" : ""}>Search</a>
```

with:

```astro
          <a href={`${base}people`} class={isActive(`${base}people`) ? "active" : ""}>People</a>
          <a href={`${base}scorecards`} class={isActive(`${base}scorecards`) ? "active" : ""}>Scorecards</a>
          <a href={`${base}search`} class={isActive(`${base}search`) ? "active" : ""}>Search</a>
```

- [ ] **Step 2: Build**

```bash
cd site && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add site/src/layouts/Layout.astro
git commit -m "Add Scorecards link to site nav"
```

---

### Task 11: Verification

- [ ] **Step 1: Run all tests**

```bash
cd site && npm test
.venv/Scripts/python.exe -m pytest -q
```

Expected: all site-side vitest tests pass; the 35 existing Python tests pass.

- [ ] **Step 2: Build clean**

```bash
cd site && npm run build
```

Expected: completes without errors; pagefind index regenerates.

- [ ] **Step 3: Smoke-test in preview**

```bash
cd site && npm run preview
```

Then visit:
- `http://localhost:4321/scorecards` — table renders, default sort by Sponsored desc, all four sortable column headers work, chamber filter buttons work.
- `http://localhost:4321/scorecards?chamber=upper&sort=partyLoyaltyRate` — Senate-only, sorted by loyalty, suppressed rates appear as `—` at the bottom.
- `http://localhost:4321/compare` — empty state + picker visible.
- `http://localhost:4321/compare?ids=ky-<some-known-rep>&ids=ky-<another>` — side-by-side metrics render.
- `http://localhost:4321/person/ky-<some-known-rep>` — stats grid renders with 4 tiles, "Compare with peers" CTA works.
- Confirm "Scorecards" link appears in the top nav between People and Search.
- Confirm a council profile (e.g. `/person/metro-council-...`) is unchanged — no stats grid, no errors.

- [ ] **Step 4: Final commit if cleanup needed**

If any tweaks were required during smoke-testing, commit them with a message like:

```bash
git commit -m "Polish: <specific tweak>"
```

---

## Self-review notes

- **Spec coverage:**
  - Profile stats grid → Task 7 ✓
  - `/scorecards` leaderboard with chamber filter + URL-state sort → Task 8 ✓
  - `/compare` side-by-side, ?ids= URL state, `<select>` picker → Task 9 ✓
  - Nav link → Task 10 ✓
  - All metrics (counts, loyalty, effectiveness, law, topSubjects, topCoSponsors) → Tasks 2–5 ✓
  - Small-N suppression (LOYALTY_MIN_N, EFFECT_MIN_N) → Tasks 3, 4 ✓
  - Null-safety for `person_id: null` → Task 2 (test) ✓
  - Independents/null party get `null` loyalty → Task 3 (test) ✓
  - Vitest fixture suite → Tasks 1–5 ✓
- **Type consistency:** `LegislatorStats`, `FixtureBill`, `FixturePerson`, `FixtureSponsor`, `FixtureMemberVote`, `FixtureVote` defined in Task 2; reused unchanged in Tasks 3–6. Public API names (`computeAllLegislatorStats`, `getLegislatorStats`, `getLeaderboard`, `getComparison`) defined in Task 6 and consumed in Tasks 7–9 with matching signatures.
- **No placeholders:** every step has either exact file paths + complete code, or an exact command + expected output. No "TBD" / "TODO" / "similar to above" stubs.
