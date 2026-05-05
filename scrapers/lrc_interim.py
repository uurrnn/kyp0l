"""Scrape Kentucky Legislative Research Commission interim joint committees.

Off-session policy work (testimony, studies, draft bills) happens in interim
joint committees that meet June through December. They aren't in Open States,
which is why this scraper exists.

Three pages, in order:

1. **Landing**: ``https://legislature.ky.gov/Committees/interim-joint-committee``
   Lists every committee with its CommitteeRSN and display name.

2. **Per-committee detail**:
   ``/Committees/Pages/Committee-Details.aspx?CommitteeRSN=<rsn>&CommitteeType=Interim%20Joint%20Committee``
   Tells us the **CommitteeDocuments id** (different number from RSN), the
   member roster (district numbers), and jurisdiction text.

3. **CommitteeDocuments**: ``https://apps.legislature.ky.gov/CommitteeDocuments/<id>``
   The gold mine. Every meeting is an ``<h3>`` (date) followed by a sibling
   ``<ul><li><a href="./<folder_id>/<filename>.pdf">``. The folder id is the
   stable per-meeting key.

We download one agenda PDF per meeting (mirrors PrimeGov pattern) and list
every other linked file as an attachment without downloading. PDF text is
extracted via :mod:`scrapers.pdf_extract` and stored under
``data/attachments/<sha>.txt`` for Pagefind.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

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


LRC_BASE = "https://legislature.ky.gov"
DOCS_BASE = "https://apps.legislature.ky.gov/CommitteeDocuments"
LANDING_URL = f"{LRC_BASE}/Committees/interim-joint-committee"
USER_AGENT = "louisville-politics-tracker (+https://github.com/local)"

SOURCE_TYPE = "lrc-interim"


@dataclass
class LrcCommittee:
    rsn: str                  # CommitteeRSN from the landing page (e.g. "29" for Education)
    name: str                 # display name from landing, e.g. "Education"
    detail_url: str
    body_id: str              # our slug, e.g. "lrc-interim-education"
    documents_id: str | None = None         # CommitteeDocuments numeric id (filled by enrich)
    member_districts: list[str] = field(default_factory=list)
    jurisdiction: str = ""

    def display_name(self) -> str:
        return f"Interim Joint Committee on {self.name}"


@dataclass
class LrcMeetingRow:
    folder_id: str            # the path segment from the first attachment URL, e.g. "41137"
    date_iso: str             # "YYYY-MM-DD"
    attachments: list[tuple[str, str]]  # [(filename, absolute_url)]


# Matches lines like "1. Welcome and call to order" — generic agenda-item heuristic.
_AGENDA_NUMBERED_RE = re.compile(r"^\s*(\d{1,2})\.\s+(.{4,200})$")


class LrcInterimScraper:
    def __init__(self, user_agent: str = USER_AGENT) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def _get(self, url: str, timeout: int = 30) -> str:
        r = self.session.get(url, timeout=timeout)
        r.raise_for_status()
        return r.text

    # --------------------------------------------------------- discovery

    def list_committees(self) -> list[LrcCommittee]:
        return parse_landing(self._get(LANDING_URL))

    def enrich_committee(self, c: LrcCommittee) -> LrcCommittee:
        """Fetch the detail page and fill in documents_id, member_districts, jurisdiction."""
        html = self._get(c.detail_url)
        parse_committee_detail(html, c)
        return c

    # --------------------------------------------------------- meetings

    def list_meetings(self, c: LrcCommittee) -> list[LrcMeetingRow]:
        if not c.documents_id:
            return []
        html = self._get(f"{DOCS_BASE}/{c.documents_id}")
        return parse_documents_page(html, base_url=f"{DOCS_BASE}/{c.documents_id}/")

    # --------------------------------------------------------- one meeting

    def fetch_meeting(
        self,
        row: LrcMeetingRow,
        c: LrcCommittee,
        attachments_dir: Path,
        sleep_seconds: float = 1.0,
    ) -> Meeting:
        """Build a Meeting from a documents-page row.

        Picks the agenda PDF (filename matches /agenda/i, falling back to first
        PDF), downloads + extracts text, and lists every other attachment without
        downloading.
        """
        agenda_idx = _pick_agenda_index(row.attachments)
        attachments_out: list[Attachment] = []
        agenda_text = ""
        agenda_sha = ""

        for i, (fname, url) in enumerate(row.attachments):
            if i == agenda_idx and url.lower().endswith(".pdf"):
                try:
                    pdf_bytes = fetch(url, timeout=60)
                except requests.RequestException:
                    pdf_bytes = b""
                if pdf_bytes:
                    sha = sha256_bytes(pdf_bytes)
                    text_file = attachments_dir / f"{sha}.txt"
                    if text_file.exists():
                        text = text_file.read_text(encoding="utf-8")
                    else:
                        text = extract_pdf_text(pdf_bytes)
                        save_extracted_text(text, sha, attachments_dir)
                    agenda_text = text
                    agenda_sha = sha
                    attachments_out.append(Attachment(
                        sha256=sha,
                        url=url,
                        mime="application/pdf",
                        template_name=fname,
                        extracted_text_path=(
                            f"data/attachments/{sha}.txt"
                            if is_meaningful_text(text) else None
                        ),
                    ))
                    if sleep_seconds:
                        time.sleep(sleep_seconds)
                    continue
            # Non-agenda or agenda fetch failure: list it without downloading.
            attachments_out.append(Attachment(
                sha256="",
                url=url,
                mime=_guess_mime(fname),
                template_name=fname,
                extracted_text_path=None,
            ))

        items = _parse_agenda_items(agenda_text) if agenda_text else []
        if not items and agenda_sha:
            items = [AgendaItem(
                item_number="1",
                file_number=None,
                title=f"Full agenda PDF ({len(row.attachments)} document(s))",
                section=None,
            )]

        meeting_id = f"lrc-interim-{c.documents_id}-{row.folder_id}"
        return Meeting(
            id=meeting_id,
            body_id=c.body_id,
            title=c.display_name(),
            date=row.date_iso,
            time=None,
            source_type=SOURCE_TYPE,
            source_url=f"{DOCS_BASE}/{c.documents_id}",
            source_meeting_id=row.folder_id,
            video_url=None,
            attachments=attachments_out,
            items=items,
        )


# ============================================================ parsers


def parse_landing(html: str) -> list[LrcCommittee]:
    """Pull every interim joint committee out of the landing page."""
    soup = BeautifulSoup(html, "lxml")
    committees: list[LrcCommittee] = []
    # lxml lowercases attribute names, so use the lowercase form here.
    for li in soup.find_all("li", attrs={"data-committeersn": True}):
        rsn = (li.get("data-committeersn") or "").strip()
        a = li.find("a", href=True)
        if not rsn or a is None:
            continue
        title_span = a.find("span", class_="list-group-item-title")
        name = (title_span.get_text(" ", strip=True) if title_span else a.get_text(" ", strip=True)).strip()
        if not name:
            continue
        href = a["href"]
        detail_url = urljoin(LRC_BASE, href)
        body_id = f"lrc-interim-{slugify(name)}"
        committees.append(LrcCommittee(
            rsn=rsn,
            name=name,
            detail_url=detail_url,
            body_id=body_id,
        ))
    # de-dup on body_id (sub-committees can share words)
    seen: set[str] = set()
    unique: list[LrcCommittee] = []
    for c in committees:
        if c.body_id in seen:
            continue
        seen.add(c.body_id)
        unique.append(c)
    return sorted(unique, key=lambda c: c.name.lower())


def parse_committee_detail(html: str, c: LrcCommittee) -> None:
    """Mutate `c` in place with documents_id, member_districts, jurisdiction."""
    soup = BeautifulSoup(html, "lxml")

    # Documents URL: <a class="block_btn" href="https://apps.legislature.ky.gov/CommitteeDocuments/<id>">
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"/CommitteeDocuments/(\d+)\b", href)
        if m:
            c.documents_id = m.group(1)
            break

    # Member roster: <a href="/Legislators/Pages/Legislator-Profile.aspx?DistrictNumber=N">
    districts: list[str] = []
    for a in soup.find_all("a", href=True):
        m = re.search(r"DistrictNumber=(\d+)", a["href"])
        if m and m.group(1) not in districts:
            districts.append(m.group(1))
    c.member_districts = districts

    # Jurisdiction text
    jur = soup.find("div", class_="jurisdiction")
    if jur is not None:
        c.jurisdiction = jur.get_text(" ", strip=True)


def parse_documents_page(html: str, base_url: str) -> list[LrcMeetingRow]:
    """Parse a CommitteeDocuments page into meeting rows.

    The structure is::

        <h3>Tuesday, December 9, 2025</h3>
        <ul>
          <li><a href="./41137/9December2025Agenda.pdf">9December2025Agenda.pdf</a></li>
          <li><a href="./41137/Other.pdf">Other.pdf</a></li>
        </ul>
        <h3>Tuesday, November 4, 2025</h3>
        <ul>...</ul>

    Some lower-down ``<h3>`` blocks ("Other Meeting Years", "Citizen Members"
    on the LRC site, etc.) are not meetings — we filter by parsing the date.
    """
    soup = BeautifulSoup(html, "lxml")
    out: list[LrcMeetingRow] = []
    seen_folders: set[str] = set()

    for h3 in soup.find_all("h3"):
        date_iso = parse_lrc_date(h3.get_text(" ", strip=True))
        if not date_iso:
            continue
        # Find the next <ul> sibling
        ul = h3.find_next_sibling()
        while ul is not None and (not isinstance(ul, Tag) or ul.name != "ul"):
            ul = ul.find_next_sibling()
        if ul is None:
            continue
        attachments: list[tuple[str, str]] = []
        folder_id = ""
        for li_a in ul.find_all("a", href=True):
            href = li_a["href"]
            url = urljoin(base_url, href)
            fname = li_a.get_text(" ", strip=True) or href.rsplit("/", 1)[-1]
            attachments.append((fname, url))
            if not folder_id:
                m = re.search(r"/(\d+)/[^/]+$", url)
                if m:
                    folder_id = m.group(1)
        if not folder_id or not attachments:
            continue
        if folder_id in seen_folders:
            continue
        seen_folders.add(folder_id)
        out.append(LrcMeetingRow(folder_id=folder_id, date_iso=date_iso, attachments=attachments))

    return out


def parse_lrc_date(s: str) -> str:
    """Convert 'Tuesday, December 9, 2025' to '2025-12-09'. Returns '' on miss."""
    s = (s or "").strip()
    for fmt in ("%A, %B %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


# ----------------------------------------------------------- helpers


def _pick_agenda_index(attachments: list[tuple[str, str]]) -> int:
    """Return the index of the agenda PDF, or 0 to fall back to the first item."""
    for i, (fname, url) in enumerate(attachments):
        low = fname.lower()
        if "agenda" in low and url.lower().endswith(".pdf"):
            return i
    # Fallback: first PDF
    for i, (_, url) in enumerate(attachments):
        if url.lower().endswith(".pdf"):
            return i
    return 0


def _guess_mime(filename: str) -> str:
    low = filename.lower()
    if low.endswith(".pdf"):
        return "application/pdf"
    if low.endswith((".pptx", ".ppt")):
        return "application/vnd.ms-powerpoint"
    if low.endswith((".docx", ".doc")):
        return "application/msword"
    if low.endswith((".xlsx", ".xls")):
        return "application/vnd.ms-excel"
    if low.endswith(".zip"):
        return "application/zip"
    return "application/octet-stream"


def _parse_agenda_items(text: str) -> list[AgendaItem]:
    """Best-effort: capture lines that start with a number + period + title.

    LRC interim agendas vary. This grabs simple "1. Welcome" / "2. Speakers"
    style outlines without trying to be too clever. The raw PDF text is also
    saved as the search corpus, so missing items isn't fatal.
    """
    if not text:
        return []
    items: list[AgendaItem] = []
    seen: set[tuple[str, str]] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or len(line) > 220:
            continue
        m = _AGENDA_NUMBERED_RE.match(line)
        if not m:
            continue
        number, title = m.group(1), m.group(2).strip()
        if not title or title.lower().startswith("page "):
            continue
        key = (number, title[:80])
        if key in seen:
            continue
        seen.add(key)
        items.append(AgendaItem(
            item_number=number,
            file_number=None,
            title=title,
            section=None,
        ))
        if len(items) >= 50:
            break
    return items


# ----------------------------------------------------------- orchestrator


def write_meeting_record(meeting: Meeting, data_root: Path) -> Path:
    year = meeting.date.split("-", 1)[0] or "unknown"
    out = data_root / "meetings" / meeting.body_id / year / f"{meeting.id}.json"
    write_json(out, {
        **meeting.to_dict(),
        "attachments": [a.to_dict() for a in meeting.attachments],
        "items": [it.to_dict() for it in meeting.items],
    })
    return out


def committee_body(c: LrcCommittee) -> Body:
    """Promote an LRC committee record into the shared Body shape."""
    return Body(
        id=c.body_id,
        name=c.display_name(),
        source_type=SOURCE_TYPE,
        source_id=c.documents_id or c.rsn,
    )


def write_committee_index(committees: list[LrcCommittee], data_root: Path) -> Path:
    """Emit data/committees/_index.json mapping committee body_id to its roster.

    Idempotent full rewrite — only ~20 committees, so re-emission is cheap.
    Read at site-build time to power the "Serves on" section on legislator
    profile pages (district-based join with KY people data).
    """
    out_dir = data_root / "committees"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, dict] = {}
    for c in committees:
        if not c.documents_id:
            continue
        payload[c.body_id] = {
            "name": c.display_name(),
            "rsn": c.rsn,
            "documents_id": c.documents_id,
            "member_districts": list(c.member_districts),
        }
    out = out_dir / "_index.json"
    write_json(out, payload)
    return out
