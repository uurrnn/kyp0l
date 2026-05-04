import { useEffect, useMemo, useState } from "preact/hooks";
import type { BillManifestItem } from "~/lib/bills-manifest";

interface Props { base: string }

const STATUS_OPTIONS: { key: string; label: string }[] = [
  { key: "pending", label: "Introduced / in committee" },
  { key: "committee-out", label: "Out of committee" },
  { key: "cross", label: "In second chamber" },
  { key: "passed", label: "Awaiting governor" },
  { key: "law", label: "Became law" },
  { key: "fail", label: "Failed / vetoed" },
];

const BODY_OPTIONS: { key: string; label: string }[] = [
  { key: "ky-house", label: "KY House" },
  { key: "ky-senate", label: "KY Senate" },
];

interface UrlState {
  subjects: string[];
  status: string | null;
  body: string | null;
  recent: number | null;
}

function readUrl(): UrlState {
  if (typeof window === "undefined") {
    return { subjects: [], status: null, body: null, recent: null };
  }
  const p = new URLSearchParams(window.location.search);
  const recentStr = p.get("recent");
  return {
    // Subjects use repeated params (?subject=A&subject=B) because subject
    // names themselves contain commas (e.g. "Education, Elementary And Secondary").
    subjects: p.getAll("subject"),
    status: p.get("status"),
    body: p.get("body"),
    recent: recentStr ? parseInt(recentStr, 10) : null,
  };
}

function writeUrl(state: UrlState) {
  const p = new URLSearchParams();
  for (const s of state.subjects) p.append("subject", s);
  if (state.status) p.set("status", state.status);
  if (state.body) p.set("body", state.body);
  if (state.recent) p.set("recent", String(state.recent));
  const q = p.toString();
  history.replaceState({}, "", `${location.pathname}${q ? "?" + q : ""}`);
}

export function BillsFilter({ base }: Props) {
  const [items, setItems] = useState<BillManifestItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [subjects, setSubjects] = useState<string[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [body, setBody] = useState<string | null>(null);
  const [recent, setRecent] = useState<number | null>(null);
  const [subjectSearch, setSubjectSearch] = useState("");

  // initial load + URL sync
  useEffect(() => {
    fetch(`${base}bills-manifest.json`)
      .then((r) => r.json())
      .then((data: BillManifestItem[]) => setItems(data))
      .catch((e) => setError(String(e)));

    const u = readUrl();
    setSubjects(u.subjects);
    setStatus(u.status);
    setBody(u.body);
    setRecent(u.recent);

    const onPop = () => {
      const u2 = readUrl();
      setSubjects(u2.subjects);
      setStatus(u2.status);
      setBody(u2.body);
      setRecent(u2.recent);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [base]);

  // write URL on state change (skip until after first load)
  useEffect(() => {
    if (!items) return;
    writeUrl({ subjects, status, body, recent });
  }, [subjects, status, body, recent, items]);

  const subjectCounts = useMemo(() => {
    const m = new Map<string, number>();
    if (!items) return m;
    for (const it of items) {
      for (const s of it.subjects) m.set(s, (m.get(s) || 0) + 1);
    }
    return m;
  }, [items]);

  const visibleSubjects = useMemo(() => {
    const q = subjectSearch.trim().toLowerCase();
    return Array.from(subjectCounts.entries())
      .filter(([s]) => !q || s.toLowerCase().includes(q))
      .sort((a, b) => b[1] - a[1]);
  }, [subjectCounts, subjectSearch]);

  const todayMs = useMemo(() => Date.now(), []);

  const filtered = useMemo(() => {
    if (!items) return [];
    return items.filter((it) => {
      if (subjects.length > 0 && !subjects.every((s) => it.subjects.includes(s))) return false;
      if (status && it.statusTone !== status) return false;
      if (body && !it.bodyIds.includes(body)) return false;
      if (recent) {
        const cutoff = todayMs - recent * 86400000;
        if (new Date(it.lastActionDate).getTime() < cutoff) return false;
      }
      return true;
    });
  }, [items, subjects, status, body, recent, todayMs]);

  const toggleSubject = (s: string) =>
    setSubjects((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]));

  const clearAll = () => {
    setSubjects([]);
    setStatus(null);
    setBody(null);
    setRecent(null);
    setSubjectSearch("");
  };

  if (error) return <p class="empty-state">Failed to load bills manifest: {error}</p>;
  if (!items) return <p class="empty-state">Loading bills…</p>;

  const hasFilter = subjects.length > 0 || !!status || !!body || !!recent;
  const SUBJECT_DISPLAY_LIMIT = 60;

  return (
    <div class="bills-layout">
      <aside class="facet-sidebar">
        <div class="facet-group">
          <div class="facet-group-header"><span>Subject</span></div>
          <input
            class="facet-search"
            type="search"
            placeholder="search subjects…"
            value={subjectSearch}
            onInput={(e) => setSubjectSearch((e.target as HTMLInputElement).value)}
          />
          <div class="facet-options">
            {visibleSubjects.slice(0, SUBJECT_DISPLAY_LIMIT).map(([s, n]) => (
              <label class="facet-option" key={s}>
                <input
                  type="checkbox"
                  checked={subjects.includes(s)}
                  onChange={() => toggleSubject(s)}
                />
                <span class="label">{s}</span>
                <span class="count">{n}</span>
              </label>
            ))}
            {visibleSubjects.length > SUBJECT_DISPLAY_LIMIT && (
              <p style="font-size: var(--text-xs); color: var(--fg-muted); margin: var(--space-2) 0 0;">
                +{visibleSubjects.length - SUBJECT_DISPLAY_LIMIT} more — refine search above
              </p>
            )}
          </div>
        </div>

        <div class="facet-group">
          <div class="facet-group-header"><span>Status</span></div>
          <div class="facet-chips">
            {STATUS_OPTIONS.map((opt) => (
              <button
                type="button"
                key={opt.key}
                class={`facet-chip ${status === opt.key ? "active" : ""}`}
                onClick={() => setStatus(status === opt.key ? null : opt.key)}
              >{opt.label}</button>
            ))}
          </div>
        </div>

        <div class="facet-group">
          <div class="facet-group-header"><span>Body</span></div>
          <div class="facet-chips">
            {BODY_OPTIONS.map((opt) => (
              <button
                type="button"
                key={opt.key}
                class={`facet-chip ${body === opt.key ? "active" : ""}`}
                onClick={() => setBody(body === opt.key ? null : opt.key)}
              >{opt.label}</button>
            ))}
          </div>
        </div>

        {hasFilter && (
          <div class="facet-group" style="border-bottom: 0;">
            <button type="button" class="facet-chip" onClick={clearAll}>Clear all filters</button>
          </div>
        )}
      </aside>

      <div>
        <div class="results-meta">
          {filtered.length.toLocaleString()} of {items.length.toLocaleString()} bills
        </div>

        {hasFilter && (
          <div class="active-filters">
            {subjects.map((s) => (
              <button class="active-filter-pill" key={s} onClick={() => toggleSubject(s)}>
                {s}<span class="x">×</span>
              </button>
            ))}
            {status && (
              <button class="active-filter-pill" onClick={() => setStatus(null)}>
                {STATUS_OPTIONS.find((o) => o.key === status)?.label || status}
                <span class="x">×</span>
              </button>
            )}
            {body && (
              <button class="active-filter-pill" onClick={() => setBody(null)}>
                {BODY_OPTIONS.find((o) => o.key === body)?.label || body}
                <span class="x">×</span>
              </button>
            )}
            {recent && (
              <button class="active-filter-pill" onClick={() => setRecent(null)}>
                Last {recent} days<span class="x">×</span>
              </button>
            )}
          </div>
        )}

        {filtered.length === 0 ? (
          <p class="empty-state">No bills match these filters.</p>
        ) : (
          <table class="bills-table">
            <thead>
              <tr>
                <th class="col-id">Bill</th>
                <th class="col-title">Title</th>
                <th class="col-subjects">Subjects</th>
                <th class="col-status">Status</th>
                <th class="col-date">Last action</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 500).map((it) => (
                <tr key={it.id}>
                  <td class="col-id"><a href={`${base}bill/${it.id}`}>{it.identifier}</a></td>
                  <td class="col-title"><a href={`${base}bill/${it.id}`}>{it.title}</a></td>
                  <td class="col-subjects">
                    {it.subjects.slice(0, 2).join(" · ")}
                    {it.subjects.length > 2 && ` +${it.subjects.length - 2}`}
                  </td>
                  <td class="col-status">
                    <span class={`status-badge ${it.statusTone}`}>{it.statusText}</span>
                  </td>
                  <td class="col-date">{it.lastActionDate}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {filtered.length > 500 && (
          <p class="results-meta" style="margin-top: var(--space-3);">
            Showing first 500. Refine filters to narrow further.
          </p>
        )}
      </div>
    </div>
  );
}
