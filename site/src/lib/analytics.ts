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

  return out;
}
