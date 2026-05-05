/**
 * Issue-tracker topic pages: per-subject digests of bills + sponsors + committees.
 *
 * Topics are anchored to the curated FEATURED_SUBJECTS list — only those 12
 * round-trip via /topic/<slug>. Everything else falls back to /bills?subject=X.
 *
 * Pure build-time derivation; no scrape, no committed artifact.
 */

import type { Bill, Body, Person } from "./data";
import {
  getBills,
  getBodies,
  getPersonByOcdId,
} from "./data";
import { billHeat } from "./heat";
import { FEATURED_SUBJECTS } from "./featured-subjects";

export function slugifySubject(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

const _slugToSubject = new Map<string, string>(
  FEATURED_SUBJECTS.map((s) => [slugifySubject(s), s]),
);

export function subjectFromSlug(slug: string): string | null {
  return _slugToSubject.get(slug) ?? null;
}

export interface TopicCardData {
  subject: string;
  slug: string;
  count: number;
}

let _allTopics: TopicCardData[] | null = null;

export function getAllTopics(): TopicCardData[] {
  if (_allTopics) return _allTopics;
  const counts = new Map<string, number>();
  for (const b of getBills()) {
    for (const s of b.subjects) {
      if (_slugToSubject.has(slugifySubject(s))) {
        counts.set(s, (counts.get(s) ?? 0) + 1);
      }
    }
  }
  _allTopics = FEATURED_SUBJECTS.map((subject) => ({
    subject,
    slug: slugifySubject(subject),
    count: counts.get(subject) ?? 0,
  }));
  return _allTopics;
}

export interface RecentAction {
  bill: Bill;
  date: string;
  description: string;
}

export interface TopSponsorRow {
  person: Person;
  count: number;
}

export interface TopicSummary {
  subject: string;
  slug: string;
  totalBills: number;
  lastActionDate: string;
  hotBills: Bill[];
  recentActions: RecentAction[];
  topSponsors: TopSponsorRow[];
  relatedCommittees: Body[];
}

const _STOPWORDS = new Set(["and", "of", "or", "the", "to", "a", "in", "for"]);

function topicKeyword(subject: string): string {
  for (const w of subject.toLowerCase().split(/[^a-z]+/)) {
    if (w.length >= 3 && !_STOPWORDS.has(w)) return w;
  }
  return "";
}

const _summaryCache = new Map<string, TopicSummary>();

export function getTopicSummary(slug: string): TopicSummary | null {
  const cached = _summaryCache.get(slug);
  if (cached) return cached;

  const subject = subjectFromSlug(slug);
  if (!subject) return null;

  const allBills = getBills();
  const bills = allBills.filter((b) => b.subjects.includes(subject));

  // hot bills — top 5 by heat
  const scored = bills.map((b) => ({ b, s: billHeat(b) }));
  scored.sort((x, y) => y.s - x.s);
  const hotBills = scored.slice(0, 5).map((x) => x.b);

  // recent actions — last 10 across the topic
  const events: RecentAction[] = [];
  for (const b of bills) {
    for (const a of b.actions) {
      events.push({ bill: b, date: a.date, description: a.description });
    }
  }
  events.sort((a, b) => b.date.localeCompare(a.date));
  const recentActions = events.slice(0, 10);

  // top sponsors — primary only, top 5
  const counts = new Map<string, number>();
  for (const b of bills) {
    for (const s of b.sponsors) {
      if (!s.primary || !s.person_id) continue;
      counts.set(s.person_id, (counts.get(s.person_id) ?? 0) + 1);
    }
  }
  const ranked = Array.from(counts.entries()).map(([personId, count]) => ({
    person: getPersonByOcdId(personId),
    count,
  })).filter((r): r is TopSponsorRow => r.person !== undefined);
  ranked.sort((a, b) => (b.count - a.count) || a.person.name.localeCompare(b.person.name));
  const topSponsors = ranked.slice(0, 5);

  // related committees — name contains topic keyword
  const kw = topicKeyword(subject);
  const relatedCommittees = kw
    ? getBodies().filter((body) => body.name.toLowerCase().includes(kw) && body.id !== "ky-house" && body.id !== "ky-senate" && body.id !== "metro-council")
    : [];

  const summary: TopicSummary = {
    subject,
    slug,
    totalBills: bills.length,
    lastActionDate: bills.length > 0 ? bills.reduce((acc, b) => b.last_action_date > acc ? b.last_action_date : acc, "") : "",
    hotBills,
    recentActions,
    topSponsors,
    relatedCommittees,
  };
  _summaryCache.set(slug, summary);
  return summary;
}
