"""Scrape Louisville Metro's PrimeGov instance via its public JSON API.

Usage (library):
    from scrapers.primegov import PrimeGovScraper
    s = PrimeGovScraper("louisvilleky")
    bodies = s.list_bodies()
    meetings = s.list_meetings(year=2026)
    for m in meetings:
        full = s.fetch_meeting(m, data_root)

Endpoints discovered while reverse-engineering the public portal JS bundles
(/Scripts/Custom/Public/_Search.js, _Upcoming.js, _Archived.js):

    GET /api/committee/GetCommitteeesListByShowInPublicPortal
        -> [{id, name}, ...]

    GET /api/v2/PublicPortal/ListUpcomingMeetings
        -> [meeting, ...]
    GET /api/v2/PublicPortal/ListUpcomingMeetingsByCommitteeId?committeeId=N
        -> filtered

    GET /api/v2/PublicPortal/ListArchivedMeetings?year=YYYY
        -> [meeting, ...]
    GET /api/v2/PublicPortal/ListArchivedMeetingsByCommitteeId?year=Y&committeeId=N
        -> filtered

    GET /api/Meeting/getcompiledfiledownloadurl?compiledFileId=N
        -> "https://pgwest.blob.core.windows.net/...signedurl..."
        Note: the response is a JSON STRING (just a quoted URL), not an object.
        Note: only PDFs (compileOutputType==1) are publicly accessible. HTML
        agendas (compileOutputType==3) return 500/UnauthorizedAccessException.

Each meeting has a documentList of generated documents. We pull the PDF
agenda where available.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import requests

from scrapers.models import (
    AgendaItem,
    Attachment,
    Body,
    Meeting,
    slugify,
    write_json,
)
from scrapers.pdf_extract import (
    extract_pdf_text,
    fetch,
    is_meaningful_text,
    save_extracted_text,
    sha256_bytes,
)

PRIMEGOV_BASE_FMT = "https://{instance}.primegov.com"
USER_AGENT = "louisville-politics-tracker (+https://github.com/local)"


# compileOutputType values observed in the wild
COMPILE_OUTPUT_PDF = 1
COMPILE_OUTPUT_HTML = 3


# Louisville's PrimeGov instance leaks operator test events into the public feed
# with titles like "EVENT 3 - NO AUTOSTART" and "EVENT 4 - NO AUTOSTART - BACK TO BACK EVENTS".
# These have agendas-but-not-really and should be filtered before any work is done.
_TEST_EVENT_RE = re.compile(r"^\s*EVENT\s+\d+\s*-\s*NO\s+AUTOSTART", re.IGNORECASE)


def _is_upstream_test_event(title: str) -> bool:
    return bool(_TEST_EVENT_RE.match(title or ""))


@dataclass
class RawMeeting:
    raw: dict[str, Any]


class PrimeGovScraper:
    def __init__(self, instance: str, user_agent: str = USER_AGENT) -> None:
        self.instance = instance
        self.base = PRIMEGOV_BASE_FMT.format(instance=instance)
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": user_agent, "Accept": "application/json"}
        )

    # ------------------------------------------------------------------ helpers

    def _get_json(self, path: str, **params: Any) -> Any:
        url = f"{self.base}{path}"
        r = self.session.get(url, params=params or None, timeout=30)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------- bodies

    def list_bodies(self) -> list[Body]:
        raw = self._get_json("/api/committee/GetCommitteeesListByShowInPublicPortal")
        bodies: list[Body] = []
        for entry in raw:
            name = (entry.get("name") or "").strip()
            if not name:
                continue
            bodies.append(
                Body(
                    id=slugify(name),
                    name=name,
                    source_type="primegov",
                    source_id=str(entry["id"]),
                )
            )
        # de-dup on slug just in case
        seen: set[str] = set()
        out: list[Body] = []
        for b in bodies:
            if b.id in seen:
                continue
            seen.add(b.id)
            out.append(b)
        return sorted(out, key=lambda b: b.name.lower())

    # ----------------------------------------------------------------- meetings

    def list_meetings_for_year(self, year: int) -> list[dict[str, Any]]:
        raw = self._get_json(
            "/api/v2/PublicPortal/ListArchivedMeetings", year=year
        )
        return [m for m in raw if not _is_upstream_test_event(m.get("title", ""))]

    def list_upcoming_meetings(self) -> list[dict[str, Any]]:
        raw = self._get_json("/api/v2/PublicPortal/ListUpcomingMeetings")
        return [m for m in raw if not _is_upstream_test_event(m.get("title", ""))]

    # ------------------------------------------------------------- one meeting

    def get_pdf_url(self, compiled_file_id: int | str) -> str | None:
        """Return the signed download URL for a compiled PDF, or None on error.

        The endpoint returns 500 + UnauthorizedAccessException for HTML
        compilations (compileOutputType==3). PDFs return a JSON-quoted URL.
        """
        url = f"{self.base}/api/Meeting/getcompiledfiledownloadurl"
        try:
            r = self.session.get(url, params={"compiledFileId": compiled_file_id}, timeout=20)
            r.raise_for_status()
        except requests.HTTPError:
            return None
        try:
            value = r.json()
        except ValueError:
            return None
        if not isinstance(value, str) or not value.startswith("http"):
            return None
        return value

    def fetch_meeting(
        self,
        raw: dict[str, Any],
        body: Body,
        attachments_dir: Path,
        sleep_seconds: float = 0.0,
    ) -> Meeting:
        """Turn a raw meeting record into a Meeting (with attachments + items).

        Downloads the agenda PDF if present, extracts text, and parses items.
        Skips re-downloading attachments whose sha256 is already on disk.
        """
        upstream_id = str(raw["id"])
        meeting_id = f"primegov-{self.instance}-{upstream_id}"
        date_iso = (raw.get("dateTime") or "").split("T", 1)[0]
        time_part = (raw.get("dateTime") or "").split("T", 1)[1][:5] if "T" in (raw.get("dateTime") or "") else None

        attachments: list[Attachment] = []
        full_text = ""
        for doc in raw.get("documentList") or []:
            if doc.get("compileOutputType") != COMPILE_OUTPUT_PDF:
                continue
            cf_id = doc["id"]
            pdf_url = self.get_pdf_url(cf_id)
            if not pdf_url:
                continue
            try:
                pdf_bytes = fetch(pdf_url, timeout=60)
            except requests.RequestException:
                continue
            sha = sha256_bytes(pdf_bytes)
            text_file = attachments_dir / f"{sha}.txt"
            if text_file.exists():
                text = text_file.read_text(encoding="utf-8")
            else:
                text = extract_pdf_text(pdf_bytes)
                save_extracted_text(text, sha, attachments_dir)
            attachments.append(
                Attachment(
                    sha256=sha,
                    url=pdf_url,
                    mime="application/pdf",
                    template_name=doc.get("templateName") or "",
                    extracted_text_path=f"data/attachments/{sha}.txt"
                    if is_meaningful_text(text)
                    else None,
                )
            )
            if is_meaningful_text(text) and len(text) > len(full_text):
                full_text = text
            if sleep_seconds:
                time.sleep(sleep_seconds)

        items = parse_agenda_items(full_text) if full_text else []

        # Public-portal meeting URL — useful for "view in PrimeGov" links from the dashboard.
        portal_url = f"{self.base}/public/Portal/Meeting?meetingTemplateId={upstream_id}"

        return Meeting(
            id=meeting_id,
            body_id=body.id,
            title=(raw.get("title") or body.name).strip(),
            date=date_iso,
            time=time_part,
            source_type="primegov",
            source_url=portal_url,
            source_meeting_id=upstream_id,
            video_url=raw.get("videoUrl") or None,
            attachments=attachments,
            items=items,
        )


# ---------------------------------------------------------------- item parsing

# Matches lines like:
#     "1.   ID 26-0030    Addresses to Council — January 29, 2026"
# pdfminer often splits the number, ID token, and title across multiple lines,
# so the parser below works in two passes against the full extracted text.
ITEM_LINE_RE = re.compile(
    r"^\s*(\d{1,3})\.\s*$|^\s*ID\s+(\d{2}-\d{4})\b(.*)$",
    re.MULTILINE,
)

SECTION_HEADERS = {
    "Addresses to the Council",
    "Council Minutes",
    "Committee Minutes",
    "Communications to the Council",
    "Consent Calendar",
    "Old Business",
    "New Business",
    "Reports of Standing Committees",
    "Reports of Special Committees",
    "Recess",
    "Adjournment",
}


def parse_agenda_items(text: str) -> list[AgendaItem]:
    """Best-effort extraction of agenda items from PDF text.

    The Metro Council format is "N.\\nID YY-NNNN <title>". pdfminer leaves the
    number on its own line, then the "ID..." line, then the title (sometimes
    on the same line, sometimes wrapped onto the next).

    For bodies without the ID-prefixed convention we still capture numbered
    items by their title — the FILE NUMBER will be None.
    """
    items: list[AgendaItem] = []
    lines = [ln.rstrip() for ln in text.splitlines()]

    current_section: str | None = None
    pending_number: str | None = None

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # Section headers — case-insensitive exact match
        if line in SECTION_HEADERS:
            current_section = line
            pending_number = None
            i += 1
            continue

        # "1." on its own line
        m_num = re.fullmatch(r"(\d{1,3})\.", line)
        if m_num:
            pending_number = m_num.group(1)
            i += 1
            continue

        # "ID YY-NNNN <title>" — title may continue on next line(s) until blank
        m_id = re.match(r"^ID\s+(\d{2}-\d{4})\s*(.*)$", line)
        if m_id:
            file_number = m_id.group(1)
            title = m_id.group(2).strip()
            j = i + 1
            while j < len(lines) and lines[j].strip() and not lines[j].strip().startswith("ID ") and not re.fullmatch(r"\d{1,3}\.", lines[j].strip()):
                # stop if we hit a section header
                if lines[j].strip() in SECTION_HEADERS:
                    break
                # heuristic: stop if line starts with another item number "12."
                title = (title + " " + lines[j].strip()).strip()
                j += 1
            items.append(
                AgendaItem(
                    item_number=pending_number or str(len(items) + 1),
                    file_number=file_number,
                    title=title,
                    section=current_section,
                )
            )
            pending_number = None
            i = j
            continue

        i += 1

    return items


# --------------------------------------------------------- iteration helpers

def list_all_meetings(
    scraper: PrimeGovScraper, years: Iterable[int], include_upcoming: bool = True
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for y in years:
        for m in scraper.list_meetings_for_year(y):
            mid = str(m["id"])
            if mid in seen:
                continue
            seen.add(mid)
            out.append(m)
    if include_upcoming:
        for m in scraper.list_upcoming_meetings():
            mid = str(m["id"])
            if mid in seen:
                continue
            seen.add(mid)
            out.append(m)
    return out


def write_meeting_record(
    meeting: Meeting, data_root: Path
) -> Path:
    year = meeting.date.split("-", 1)[0] or "unknown"
    out = data_root / "meetings" / meeting.body_id / year / f"{meeting.id}.json"
    write_json(out, {
        **meeting.to_dict(),
        "attachments": [a.to_dict() for a in meeting.attachments],
        "items": [it.to_dict() for it in meeting.items],
    })
    return out
