import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// /site/src/lib/data.ts -> /site/src/lib -> /site/src -> /site -> /<repo>
const REPO_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  ".."
);
const DATA_ROOT = path.join(REPO_ROOT, "data");
const MEETINGS_DIR = path.join(DATA_ROOT, "meetings");
const BILLS_DIR = path.join(DATA_ROOT, "bills");
const ATTACHMENTS_DIR = path.join(DATA_ROOT, "attachments");
const PEOPLE_DIR = path.join(DATA_ROOT, "people");
const PEOPLE_INDEX_PATH = path.join(PEOPLE_DIR, "_index.json");
const BODIES_PATH = path.join(DATA_ROOT, "bodies.json");

export type SourceType = "primegov" | "ksba" | "openstates";

export interface Body {
  id: string;
  name: string;
  source_type: SourceType;
  source_id: string;
}

export interface Attachment {
  sha256: string;
  url: string;
  mime: string;
  template_name: string;
  extracted_text_path: string | null;
}

export interface AgendaItem {
  item_number: string;
  file_number: string | null;
  title: string;
  section: string | null;
}

export interface Meeting {
  id: string;
  body_id: string;
  title: string;
  date: string; // ISO YYYY-MM-DD
  time: string | null;
  source_type: SourceType;
  source_url: string;
  source_meeting_id: string;
  video_url: string | null;
  attachments: Attachment[];
  items: AgendaItem[];
}

let _bodies: Body[] | null = null;
let _bodiesById: Map<string, Body> | null = null;
let _meetings: Meeting[] | null = null;

export function getBodies(): Body[] {
  if (_bodies) return _bodies;
  if (!fs.existsSync(BODIES_PATH)) {
    _bodies = [];
    _bodiesById = new Map();
    return _bodies;
  }
  const raw = JSON.parse(fs.readFileSync(BODIES_PATH, "utf-8")) as Record<string, Body>;
  _bodies = Object.values(raw).sort((a, b) => a.name.localeCompare(b.name));
  _bodiesById = new Map(_bodies.map((b) => [b.id, b]));
  return _bodies;
}

export function getBodyById(id: string): Body | undefined {
  if (!_bodiesById) getBodies();
  return _bodiesById!.get(id);
}

function* walkJson(dir: string): Generator<string> {
  if (!fs.existsSync(dir)) return;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      yield* walkJson(full);
    } else if (entry.isFile() && entry.name.endsWith(".json")) {
      yield full;
    }
  }
}

export function getMeetings(): Meeting[] {
  if (_meetings) return _meetings;
  const out: Meeting[] = [];
  for (const file of walkJson(MEETINGS_DIR)) {
    try {
      const raw = JSON.parse(fs.readFileSync(file, "utf-8")) as Meeting;
      out.push(raw);
    } catch {
      // skip malformed
    }
  }
  out.sort((a, b) => (b.date + (b.time ?? "")).localeCompare(a.date + (a.time ?? "")));
  _meetings = out;
  return _meetings;
}

export function getMeetingsByBody(bodyId: string): Meeting[] {
  return getMeetings().filter((m) => m.body_id === bodyId);
}

export function getMeetingById(id: string): Meeting | undefined {
  return getMeetings().find((m) => m.id === id);
}

export function readExtractedText(extractedPath: string | null): string {
  if (!extractedPath) return "";
  // extractedPath is repo-relative like "data/attachments/<sha>.txt"
  const abs = path.join(REPO_ROOT, extractedPath);
  if (!fs.existsSync(abs)) return "";
  try {
    return fs.readFileSync(abs, "utf-8");
  } catch {
    return "";
  }
}

// ----------------------------------------------------------- Bills

export type ChamberState = "introduced" | "in_committee" | "passed_committee" | "passed" | "failed";
export type GovernorState = "signed" | "vetoed";

export interface Sponsor {
  name: string;
  party: string | null;
  district: string | null;
  primary: boolean;
  person_id?: string | null;
}

export interface Action {
  date: string;
  description: string;
  chamber: "lower" | "upper" | null;
  classification: string[];
}

export interface MemberVote {
  name: string;
  option: string;
  person_id?: string | null;
}

export interface Vote {
  motion: string;
  date: string;
  chamber: "lower" | "upper";
  result: string;
  counts: { yes: number; no: number; abstain: number; "not voting": number };
  member_votes: MemberVote[];
}

export interface Bill {
  id: string;
  body_ids: string[];
  session: string;
  identifier: string;
  title: string;
  abstract: string | null;
  classification: string[];
  sponsors: Sponsor[];
  actions: Action[];
  votes: Vote[];
  subjects: string[];
  chamber_progress: {
    lower: ChamberState | null;
    upper: ChamberState | null;
    governor: GovernorState | null;
  };
  current_status: string;
  last_action_date: string;
  source_url: string;
  openstates_id: string;
}

let _bills: Bill[] | null = null;

export function getBills(): Bill[] {
  if (_bills) return _bills;
  const out: Bill[] = [];
  for (const file of walkJson(BILLS_DIR)) {
    try {
      const raw = JSON.parse(fs.readFileSync(file, "utf-8")) as Bill;
      out.push(raw);
    } catch {
      // skip malformed
    }
  }
  out.sort((a, b) => b.last_action_date.localeCompare(a.last_action_date));
  _bills = out;
  return _bills;
}

export function getBillById(id: string): Bill | undefined {
  return getBills().find((b) => b.id === id);
}

export function getBillsByBody(bodyId: string): Bill[] {
  return getBills().filter((b) => b.body_ids.includes(bodyId));
}

export function getRecentBills(n: number): Bill[] {
  return getBills().slice(0, n);
}

// ----------------------------------------------------------- session status

export interface SessionStatus {
  /** True if bills have moved in the last RECESS_DAYS days. */
  inSession: boolean;
  /** Most recent bill action date across all bills (ISO YYYY-MM-DD), or "" if none. */
  lastActionDate: string;
  /** Days since lastActionDate (Inf if no actions). */
  daysSinceLastAction: number;
  /** Active session identifier from the most recent bill, or null. */
  session: string | null;
}

// 7 days is tight enough to flag recess promptly but loose enough that a
// regular session weekend or 4-day pause doesn't trip it.
const RECESS_DAYS = 7;

export function getSessionStatus(now: Date = new Date()): SessionStatus {
  const bills = getBills();
  if (bills.length === 0) {
    return { inSession: false, lastActionDate: "", daysSinceLastAction: Infinity, session: null };
  }
  // bills is already sorted by last_action_date desc.
  const last = bills[0].last_action_date || "";
  if (!last) {
    return { inSession: false, lastActionDate: "", daysSinceLastAction: Infinity, session: bills[0].session };
  }
  const lastMs = Date.parse(last + "T00:00:00Z");
  const daysSince = Number.isFinite(lastMs)
    ? (now.getTime() - lastMs) / (1000 * 60 * 60 * 24)
    : Infinity;
  return {
    inSession: daysSince <= RECESS_DAYS,
    lastActionDate: last,
    daysSinceLastAction: daysSince,
    session: bills[0].session,
  };
}

// ----------------------------------------------------------- formatting

export function formatMeetingDate(m: Meeting): string {
  // Render as e.g. "Apr 21, 2026 6:00 PM"
  if (!m.date) return "";
  const [y, mo, d] = m.date.split("-").map(Number);
  if (!y || !mo || !d) return m.date;
  const monthNames = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  const date = `${monthNames[mo - 1]} ${d}, ${y}`;
  if (!m.time) return date;
  // m.time is "HH:MM" 24h
  const [hh, mm] = m.time.split(":").map(Number);
  if (Number.isNaN(hh)) return date;
  const ampm = hh >= 12 ? "PM" : "AM";
  const h12 = hh === 0 ? 12 : hh > 12 ? hh - 12 : hh;
  return `${date} ${h12}:${String(mm).padStart(2, "0")} ${ampm}`;
}

export type StatusTone = "pending" | "committee-out" | "cross" | "passed" | "law" | "fail";

export function billStatusTone(bill: Bill): StatusTone {
  const cp = bill.chamber_progress;
  const classifs = new Set(bill.actions.flatMap((a) => a.classification));
  const becameLaw = classifs.has("became-law") || cp.governor === "signed";
  const vetoOverride = cp.governor === "vetoed" && classifs.has("veto-override-passage");
  if (becameLaw || vetoOverride) return "law";
  if (cp.governor === "vetoed") return "fail";
  if (cp.lower === "passed" && cp.upper === "passed") return "passed";
  if (cp.lower === "failed" || cp.upper === "failed") return "fail";
  if (cp.lower === "passed" || cp.upper === "passed") return "cross";
  if (cp.lower === "passed_committee" || cp.upper === "passed_committee") return "committee-out";
  return "pending";
}

// ----------------------------------------------------------- People

export interface PersonContact {
  addresses: { classification?: string; address?: string }[];
  phones: { classification?: string; voice?: string }[];
  emails: string[];
  links: string[];
}

export interface Person {
  id: string;                 // our slug, also the URL segment
  source: "openstates" | "metro-council";
  source_id: string;          // ocd-person/... for openstates, self-id for council
  name: string;
  body_id: string;
  chamber: "lower" | "upper" | null;
  party: string | null;
  district: string | null;
  active: boolean;
  photo_url: string | null;
  contact: PersonContact;
  sources: string[];
}

let _people: Person[] | null = null;
let _peopleById: Map<string, Person> | null = null;
let _peopleIndex: Map<string, string> | null = null;  // upstream source_id -> our slug

export function getPeople(): Person[] {
  if (_people) return _people;
  const out: Person[] = [];
  if (!fs.existsSync(PEOPLE_DIR)) {
    _people = [];
    _peopleById = new Map();
    return _people;
  }
  for (const entry of fs.readdirSync(PEOPLE_DIR, { withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith(".json")) continue;
    if (entry.name.startsWith("_")) continue;  // index + seed files
    try {
      const raw = JSON.parse(fs.readFileSync(path.join(PEOPLE_DIR, entry.name), "utf-8")) as Person;
      out.push(raw);
    } catch {
      // skip malformed
    }
  }
  out.sort((a, b) => a.name.localeCompare(b.name));
  _people = out;
  _peopleById = new Map(out.map((p) => [p.id, p]));
  return _people;
}

export function getPersonById(id: string): Person | undefined {
  if (!_peopleById) getPeople();
  return _peopleById!.get(id);
}

function loadPeopleIndex(): Map<string, string> {
  if (_peopleIndex) return _peopleIndex;
  if (!fs.existsSync(PEOPLE_INDEX_PATH)) {
    _peopleIndex = new Map();
    return _peopleIndex;
  }
  try {
    const raw = JSON.parse(fs.readFileSync(PEOPLE_INDEX_PATH, "utf-8")) as Record<string, string>;
    _peopleIndex = new Map(Object.entries(raw));
  } catch {
    _peopleIndex = new Map();
  }
  return _peopleIndex;
}

/** Resolve an upstream `person_id` (e.g. "ocd-person/...") to our slug, or null. */
export function resolvePersonSlug(personId: string | null | undefined): string | null {
  if (!personId) return null;
  const idx = loadPeopleIndex();
  return idx.get(personId) ?? null;
}

export interface PersonSponsorship {
  bill: Bill;
  primary: boolean;
}

let _bySponsorBuilt = false;
const _bySponsor: Map<string, PersonSponsorship[]> = new Map();

function buildSponsorshipIndex(): void {
  if (_bySponsorBuilt) return;
  for (const bill of getBills()) {
    for (const s of bill.sponsors) {
      const slug = resolvePersonSlug(s.person_id);
      if (!slug) continue;
      const arr = _bySponsor.get(slug) ?? [];
      arr.push({ bill, primary: s.primary });
      _bySponsor.set(slug, arr);
    }
  }
  _bySponsorBuilt = true;
}

export function getBillsSponsoredBy(personSlug: string): PersonSponsorship[] {
  buildSponsorshipIndex();
  const out = _bySponsor.get(personSlug) ?? [];
  return [...out].sort((a, b) => b.bill.last_action_date.localeCompare(a.bill.last_action_date));
}

export interface PersonVoteRow {
  bill: Bill;
  vote: Vote;
  option: string;
}

let _byVoterBuilt = false;
const _byVoter: Map<string, PersonVoteRow[]> = new Map();

function buildVoterIndex(): void {
  if (_byVoterBuilt) return;
  for (const bill of getBills()) {
    for (const vote of bill.votes) {
      for (const mv of vote.member_votes) {
        const slug = resolvePersonSlug(mv.person_id);
        if (!slug) continue;
        const arr = _byVoter.get(slug) ?? [];
        arr.push({ bill, vote, option: mv.option });
        _byVoter.set(slug, arr);
      }
    }
  }
  _byVoterBuilt = true;
}

export function getMemberVotesByPerson(personSlug: string): PersonVoteRow[] {
  buildVoterIndex();
  const out = _byVoter.get(personSlug) ?? [];
  return [...out].sort((a, b) => b.vote.date.localeCompare(a.vote.date));
}

export function bodyLabelForPerson(p: Person): string {
  const body = getBodyById(p.body_id);
  return body?.name ?? p.body_id;
}

export function partyAbbrev(party: string | null | undefined): string {
  if (!party) return "";
  const p = party.toLowerCase();
  if (p.startsWith("dem")) return "D";
  if (p.startsWith("rep")) return "R";
  if (p.startsWith("ind")) return "I";
  return party.slice(0, 1).toUpperCase();
}

export const dataPaths = {
  REPO_ROOT,
  DATA_ROOT,
  MEETINGS_DIR,
  BILLS_DIR,
  ATTACHMENTS_DIR,
  PEOPLE_DIR,
  BODIES_PATH,
};
