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

export const dataPaths = {
  REPO_ROOT,
  DATA_ROOT,
  MEETINGS_DIR,
  BILLS_DIR,
  ATTACHMENTS_DIR,
  BODIES_PATH,
};
