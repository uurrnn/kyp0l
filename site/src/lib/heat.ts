/**
 * Bill "heat" score — how live a bill looks right now, derived purely from
 * upstream signals (no analytics, no external calls). All inputs come straight
 * off the Bill JSON; the score is recomputed on every site build.
 *
 * Components each normalize to [0, 1]; the final score is a weighted sum.
 * Weights live in HEAT_WEIGHTS so they're easy to tune in one place.
 */

import type { Bill } from "./data";
import { billStatusTone, getBills } from "./data";
import { FEATURED_SUBJECTS } from "./featured-subjects";

export const HEAT_WEIGHTS = {
  recency: 0.30,
  actionDensity: 0.20,
  voteMomentum: 0.20,
  coalitionBreadth: 0.10,
  milestoneBoost: 0.15,
  topicSalience: 0.05,
} as const;

const RECENCY_TAU_DAYS = 7;       // exponential decay constant
const DENSITY_WINDOW_DAYS = 14;
const DENSITY_SATURATION = 8;     // 8 actions in 14 days = full burst
const VOTE_SATURATION = 4;        // 4 floor votes = saturated
const SPONSOR_SATURATION = 25;    // 25 cosponsors = caucus-wide
const LAW_HOT_WINDOW_DAYS = 14;   // signed bills cool out of milestone after this

const _featuredSet = new Set(FEATURED_SUBJECTS);

function parseDate(iso: string | null | undefined): number | null {
  if (!iso) return null;
  // ISO YYYY-MM-DD; treat as UTC midnight to keep things deterministic.
  const t = Date.parse(iso.length === 10 ? iso + "T00:00:00Z" : iso);
  return Number.isFinite(t) ? t : null;
}

function daysBetween(later: number, earlier: number): number {
  return (later - earlier) / (1000 * 60 * 60 * 24);
}

export interface HeatBreakdown {
  score: number;
  recency: number;
  actionDensity: number;
  voteMomentum: number;
  coalitionBreadth: number;
  milestoneBoost: number;
  topicSalience: number;
}

/** Compute the heat breakdown for a single bill. Pure; same inputs → same output. */
export function billHeatBreakdown(bill: Bill, now: Date = new Date()): HeatBreakdown {
  const nowMs = now.getTime();

  // recency
  const lastMs = parseDate(bill.last_action_date);
  const recency = lastMs == null
    ? 0
    : Math.exp(-Math.max(0, daysBetween(nowMs, lastMs)) / RECENCY_TAU_DAYS);

  // actionDensity
  const densityCutoffMs = nowMs - DENSITY_WINDOW_DAYS * 24 * 60 * 60 * 1000;
  let recentActions = 0;
  for (const a of bill.actions) {
    const t = parseDate(a.date);
    if (t != null && t >= densityCutoffMs) recentActions++;
  }
  const actionDensity = Math.min(1, recentActions / DENSITY_SATURATION);

  // voteMomentum
  const voteMomentum = Math.min(1, bill.votes.length / VOTE_SATURATION);

  // coalitionBreadth
  const coalitionBreadth = Math.min(1, bill.sponsors.length / SPONSOR_SATURATION);

  // milestoneBoost — cool failed bills, prefer recent passages, cap signed bills
  const tone = billStatusTone(bill);
  let milestoneBoost: number;
  if (tone === "fail") {
    milestoneBoost = 0;
  } else if (tone === "law") {
    // Stay hot only if the law was made recently — old laws are history, not news.
    const becameHotWindowMs = nowMs - LAW_HOT_WINDOW_DAYS * 24 * 60 * 60 * 1000;
    const recentlySignedOrLawed = bill.actions.some((a) => {
      const t = parseDate(a.date);
      if (t == null || t < becameHotWindowMs) return false;
      return a.classification.includes("executive-signature") ||
        a.classification.includes("became-law") ||
        a.classification.includes("veto-override-passage");
    });
    milestoneBoost = recentlySignedOrLawed ? 1.0 : 0.4;
  } else if (tone === "passed") {
    milestoneBoost = 0.8;
  } else if (tone === "cross") {
    milestoneBoost = 0.5;
  } else if (tone === "committee-out") {
    milestoneBoost = 0.3;
  } else {
    milestoneBoost = 0.1;
  }

  // topicSalience
  const topicSalience = bill.subjects.some((s) => _featuredSet.has(s)) ? 1 : 0;

  const score =
    HEAT_WEIGHTS.recency          * recency +
    HEAT_WEIGHTS.actionDensity    * actionDensity +
    HEAT_WEIGHTS.voteMomentum     * voteMomentum +
    HEAT_WEIGHTS.coalitionBreadth * coalitionBreadth +
    HEAT_WEIGHTS.milestoneBoost   * milestoneBoost +
    HEAT_WEIGHTS.topicSalience    * topicSalience;

  return {
    score,
    recency,
    actionDensity,
    voteMomentum,
    coalitionBreadth,
    milestoneBoost,
    topicSalience,
  };
}

export function billHeat(bill: Bill, now?: Date): number {
  return billHeatBreakdown(bill, now).score;
}

let _hotCache: { now: number; bills: Bill[] } | null = null;

/** Top-N bills by heat. Cached per-build (the `now` slice is captured once). */
export function getHotBills(n: number, now: Date = new Date()): Bill[] {
  if (_hotCache && _hotCache.now === now.getTime()) {
    return _hotCache.bills.slice(0, n);
  }
  const scored = getBills().map((b) => ({ b, s: billHeat(b, now) }));
  scored.sort((x, y) => y.s - x.s);
  const ranked = scored.map((x) => x.b);
  _hotCache = { now: now.getTime(), bills: ranked };
  return ranked.slice(0, n);
}
