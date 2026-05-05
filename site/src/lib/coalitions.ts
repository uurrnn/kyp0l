/**
 * Sponsor coalition data — who co-sponsors with whom across all bills.
 *
 * Pure build-time derivation over getBills() + getPeople(). One pass produces
 * pair counts; the public API exposes top pairs, most-connected legislators,
 * within-vs-cross-party split, and a per-person ranked partner list.
 */

import type { Person } from "./data";
import { getBills, getPeople, getPersonByOcdId } from "./data";

export interface CoalitionPair {
  a: Person;
  b: Person;
  count: number;
  crossParty: boolean;
}

export interface ConnectedRow {
  person: Person;
  partners: number;     // distinct unique co-sponsor partners
  totalEdges: number;   // sum of edge weights (bills × partners)
}

export interface PartyMix {
  withinParty: number;  // count of pair-billings where both share normalized party
  crossParty: number;   // count of pair-billings where parties differ (and both known)
  unknown: number;      // count where at least one party not D/R
  byChamber: Record<"lower" | "upper", { within: number; cross: number; unknown: number }>;
}

export interface CoalitionPartner {
  person: Person;
  count: number;
  crossParty: boolean;
}

interface CoalitionData {
  pairs: CoalitionPair[];
  connected: ConnectedRow[];
  partyMix: PartyMix;
  byPerson: Map<string, CoalitionPartner[]>;
}

let _cached: CoalitionData | null = null;

function normalizeParty(p: string | null): "D" | "R" | "I" | null {
  if (!p) return null;
  const lower = p.toLowerCase();
  if (lower.startsWith("dem")) return "D";
  if (lower.startsWith("rep")) return "R";
  if (lower.startsWith("ind")) return "I";
  return null;
}

function pairKey(slugA: string, slugB: string): string {
  return slugA < slugB ? `${slugA}|${slugB}` : `${slugB}|${slugA}`;
}

function compute(): CoalitionData {
  const bills = getBills();
  const peopleBySlug = new Map<string, Person>();
  for (const p of getPeople()) peopleBySlug.set(p.id, p);

  const pairCount = new Map<string, number>();
  const partnersOf = new Map<string, Map<string, number>>();   // slug → partner slug → count

  // Track chamber attribution for the party-mix counter. We attribute each
  // pair-billing to a chamber by looking up the *originating* chamber: lower
  // if either sponsor is in the House and the bill_id starts with hb/hcr/hjr,
  // otherwise upper. Cheaper proxy: just take the first non-null chamber from
  // the pair. Failing that, skip the row.
  const partyMix: PartyMix = {
    withinParty: 0,
    crossParty: 0,
    unknown: 0,
    byChamber: {
      lower: { within: 0, cross: 0, unknown: 0 },
      upper: { within: 0, cross: 0, unknown: 0 },
    },
  };

  for (const bill of bills) {
    // Resolve sponsor person_ids to our slugs once per bill.
    const slugs: string[] = [];
    for (const s of bill.sponsors) {
      if (!s.person_id) continue;
      const partner = getPersonByOcdId(s.person_id);
      if (partner) slugs.push(partner.id);
    }
    if (slugs.length < 2) continue;

    // Dedup (a sponsor could appear twice in malformed data)
    const unique = Array.from(new Set(slugs));

    for (let i = 0; i < unique.length; i++) {
      for (let j = i + 1; j < unique.length; j++) {
        const k = pairKey(unique[i], unique[j]);
        pairCount.set(k, (pairCount.get(k) ?? 0) + 1);

        const aSlug = unique[i];
        const bSlug = unique[j];
        const aMap = partnersOf.get(aSlug) ?? new Map();
        aMap.set(bSlug, (aMap.get(bSlug) ?? 0) + 1);
        partnersOf.set(aSlug, aMap);
        const bMap = partnersOf.get(bSlug) ?? new Map();
        bMap.set(aSlug, (bMap.get(aSlug) ?? 0) + 1);
        partnersOf.set(bSlug, bMap);

        const aPerson = peopleBySlug.get(aSlug);
        const bPerson = peopleBySlug.get(bSlug);
        if (!aPerson || !bPerson) continue;

        const ap = normalizeParty(aPerson.party);
        const bp = normalizeParty(bPerson.party);
        const chamber = aPerson.chamber === "lower" || bPerson.chamber === "lower"
          ? "lower"
          : aPerson.chamber === "upper" || bPerson.chamber === "upper"
            ? "upper"
            : null;

        if (ap === null || bp === null || ap === "I" || bp === "I") {
          partyMix.unknown++;
          if (chamber) partyMix.byChamber[chamber].unknown++;
        } else if (ap === bp) {
          partyMix.withinParty++;
          if (chamber) partyMix.byChamber[chamber].within++;
        } else {
          partyMix.crossParty++;
          if (chamber) partyMix.byChamber[chamber].cross++;
        }
      }
    }
  }

  // Build CoalitionPair list, sorted desc by count
  const pairs: CoalitionPair[] = [];
  for (const [key, count] of pairCount) {
    const [aSlug, bSlug] = key.split("|");
    const a = peopleBySlug.get(aSlug);
    const b = peopleBySlug.get(bSlug);
    if (!a || !b) continue;
    const ap = normalizeParty(a.party);
    const bp = normalizeParty(b.party);
    const crossParty = ap !== null && bp !== null && ap !== "I" && bp !== "I" && ap !== bp;
    pairs.push({ a, b, count, crossParty });
  }
  pairs.sort((x, y) => (y.count - x.count) || x.a.name.localeCompare(y.a.name));

  // Most connected — by unique partners (and by total weighted edges as tiebreaker)
  const connected: ConnectedRow[] = [];
  for (const [slug, partnerMap] of partnersOf) {
    const person = peopleBySlug.get(slug);
    if (!person) continue;
    let totalEdges = 0;
    for (const v of partnerMap.values()) totalEdges += v;
    connected.push({ person, partners: partnerMap.size, totalEdges });
  }
  connected.sort((x, y) => (y.partners - x.partners) || (y.totalEdges - x.totalEdges) || x.person.name.localeCompare(y.person.name));

  // Per-person partner lists
  const byPerson = new Map<string, CoalitionPartner[]>();
  for (const [slug, partnerMap] of partnersOf) {
    const me = peopleBySlug.get(slug);
    if (!me) continue;
    const myParty = normalizeParty(me.party);
    const list: CoalitionPartner[] = [];
    for (const [partnerSlug, count] of partnerMap) {
      const partner = peopleBySlug.get(partnerSlug);
      if (!partner) continue;
      const theirParty = normalizeParty(partner.party);
      const crossParty = myParty !== null && theirParty !== null && myParty !== "I" && theirParty !== "I" && myParty !== theirParty;
      list.push({ person: partner, count, crossParty });
    }
    list.sort((x, y) => (y.count - x.count) || x.person.name.localeCompare(y.person.name));
    byPerson.set(slug, list);
  }

  return { pairs, connected, partyMix, byPerson };
}

export function getCoalitionData(): CoalitionData {
  if (!_cached) _cached = compute();
  return _cached;
}

export function getCoalitionPartners(slug: string): CoalitionPartner[] {
  return getCoalitionData().byPerson.get(slug) ?? [];
}
