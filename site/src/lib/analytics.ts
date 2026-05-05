/**
 * Per-legislator analytics derived at build time from bills + people.
 * Pure functions; same inputs → same outputs. Mirrors heat.ts in shape.
 */

export interface LegislatorStats {
  personSlug: string;
  chamber: "lower" | "upper" | null;
  party: string | null;
  billsPrimarySponsored: number;
  billsCoSponsored: number;
  votesCast: number;
  votesParticipated: number;
  partyLoyaltyRate: number | null;
  effectivenessRate: number | null;
  lawRate: number | null;
  topSubjects: string[];
  topCoSponsors: { personId: string; count: number }[];
}

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

export const LOYALTY_MIN_N = 20;
export const EFFECT_MIN_N = 5;

function normalizeParty(p: string | null): "D" | "R" | "I" | null {
  if (!p) return null;
  const lower = p.toLowerCase();
  if (lower.startsWith("dem")) return "D";
  if (lower.startsWith("rep")) return "R";
  if (lower.startsWith("ind")) return "I";
  return null;
}

function pastFirstChamber(progress: FixtureBill["chamber_progress"]): boolean {
  if (progress.governor === "signed") return true;
  if (progress.lower === "passed") return true;
  if (progress.upper === "passed") return true;
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

function topN<K>(counts: Map<K, number>, n: number, tieBreaker: (a: K, b: K) => number): { key: K; count: number }[] {
  const entries = Array.from(counts.entries()).map(([key, count]) => ({ key, count }));
  entries.sort((a, b) => (b.count - a.count) || tieBreaker(a.key, b.key));
  return entries.slice(0, n);
}

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

  // loyalty pass: per vote, find each party's majority choice and compare
  // each member's choice against their own-party majority.
  const matched = new Map<string, number>();
  const denom = new Map<string, number>();

  const slugParty = new Map<string, "D" | "R" | "I" | null>();
  for (const p of people) slugParty.set(p.id, normalizeParty(p.party));

  for (const bill of bills) {
    for (const vote of bill.votes) {
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

  // subjects + co-sponsors
  const subjectCounts = new Map<string, Map<string, number>>();
  const coCounts = new Map<string, Map<string, number>>();
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

  return out;
}

// ----- public API: real data path

import { getBills, getPeople } from "./data";

let _allStats: Map<string, LegislatorStats> | null = null;

export function computeAllLegislatorStats(): Map<string, LegislatorStats> {
  if (_allStats) return _allStats;

  const bills = getBills();
  const allPeople = getPeople();
  const targetPeople = allPeople.filter((p) => p.source === "openstates");

  // Build the upstream-id → our-slug index across ALL people so co-sponsor lookups
  // resolve even if the other party isn't in our `targetPeople` slice.
  const idx = new Map<string, string>();
  for (const p of allPeople) idx.set(p.source_id, p.id);

  const fixturePeople: FixturePerson[] = targetPeople.map((p) => ({
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
    sponsors: b.sponsors.map((s) => ({
      person_id: s.person_id ?? null,
      party: s.party,
      primary: s.primary,
    })),
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
