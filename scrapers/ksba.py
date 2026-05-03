"""Scrape JCPS Board of Education meetings via the KSBA Public Portal.

KSBA (Kentucky School Boards Association) hosts board meeting materials for
many KY districts at portal.ksba.org/public. The original plan assumed
JCPS uses BoardDocs; that was wrong. JCPS uses KSBA, agency id 89.

Agency page lists meetings (paginated via ASP.NET PostBack — Phase 1 fetches
only page 1 = the 25 most recent, ~12 months for a board that meets ~2x/mo).
Each meeting page contains:

- Inline structured agenda items, each numbered with a Roman/letter outline
  (II., II.A., III.B., etc.) inside <span style="color: #990033">.
- A flat list of attached PDFs (DisplayAttachment.aspx?AttachmentID=N) with
  human-readable titles. PDFs are public, no auth needed.
- Rich rationale + "Recommended Motion" + vote outcome text inline.

The full meeting page text becomes the search corpus directly — no PDF
extraction needed for the item-level data, since the HTML already has it.
We still record attachment URLs so the dashboard can deep-link to PDFs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from scrapers.models import (
    AgendaItem,
    Attachment,
    Body,
    Meeting,
    write_json,
)
from scrapers.pdf_extract import (
    is_meaningful_text,
    save_extracted_text,
    sha256_bytes,
)


KSBA_BASE = "https://portal.ksba.org/public"
USER_AGENT = "louisville-politics-tracker (+https://github.com/local)"


# Outline numbers that head an agenda item: I. / II.A. / III.A.B. / X.S.
# Anchored to the trimmed start of a span's text content.
_OUTLINE_RE = re.compile(r"^([IVXLCDM]{1,5}(?:\.[A-Z]{1,3})*)\.\s*(.+)$")


@dataclass
class KsbaMeetingRow:
    """A row pulled from the agency page's Board-meetings-table."""

    public_meeting_id: str
    href: str               # relative, e.g. "Meeting.aspx?...&PublicMeetingID=N"
    date: str               # ISO YYYY-MM-DD
    time: str | None        # 24h HH:MM
    title: str              # e.g. "Regular Business Meeting"
    location: str
    meeting_type: str       # e.g. "Regular Meeting", "Special Meeting"
    minutes_href: str | None


class KsbaScraper:
    def __init__(self, public_agency_id: int | str, agency_label: str, user_agent: str = USER_AGENT) -> None:
        self.agency_id = str(public_agency_id)
        self.agency_label = agency_label  # e.g. "JCPS Board of Education"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    # ------------------------------------------------------------------ bodies

    def body(self) -> Body:
        from scrapers.models import slugify
        return Body(
            id=slugify(self.agency_label),
            name=self.agency_label,
            source_type="ksba",
            source_id=self.agency_id,
        )

    # ----------------------------------------------------------- meeting list

    def list_meeting_rows(self) -> list[KsbaMeetingRow]:
        """Return the most-recent page of meetings.

        TODO: ASP.NET __doPostBack pagination for older meetings. Phase 1
        scope is ~12 months which fits in page 1.
        """
        url = f"{KSBA_BASE}/Agency.aspx"
        r = self.session.get(url, params={"PublicAgencyID": self.agency_id}, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        table = soup.find("table", id="Board-meetings-table")
        if table is None:
            return []

        rows: list[KsbaMeetingRow] = []
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 4:
                continue
            # Cell 0: "MM/DD/YYYY HH:MM AM/PM" plus a meeting link inside it
            date_cell, title_cell, location_cell, type_cell, *rest = cells
            link = date_cell.find("a", href=lambda h: h and "Meeting.aspx" in h)
            if link is None:
                continue
            href = link["href"]
            mid_match = re.search(r"PublicMeetingID=(\d+)", href)
            if not mid_match:
                continue

            iso_date, time24 = _parse_us_datetime(date_cell.get_text(" ", strip=True))
            minutes_href = None
            for c in rest:
                a = c.find("a", href=lambda h: h and "MeetingMinutes" in h)
                if a:
                    minutes_href = a["href"]
                    break

            rows.append(
                KsbaMeetingRow(
                    public_meeting_id=mid_match.group(1),
                    href=href,
                    date=iso_date,
                    time=time24,
                    title=title_cell.get_text(" ", strip=True),
                    location=location_cell.get_text(" ", strip=True),
                    meeting_type=type_cell.get_text(" ", strip=True),
                    minutes_href=minutes_href,
                )
            )
        return rows

    # -------------------------------------------------------- one meeting

    def fetch_meeting(
        self, row: KsbaMeetingRow, body: Body, attachments_dir: Path
    ) -> Meeting:
        meeting_url = urljoin(f"{KSBA_BASE}/", row.href)
        r = self.session.get(meeting_url, timeout=45)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        items = _extract_agenda_items(soup)
        attachments = _extract_attachments(soup)

        # Save full visible meeting text as the search corpus for this meeting.
        # We strip scripts/styles first so Pagefind sees only meaningful text.
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        meeting_text = soup.get_text(" ", strip=True)
        text_bytes = meeting_text.encode("utf-8")
        sha = sha256_bytes(text_bytes)
        if not (attachments_dir / f"{sha}.txt").exists():
            save_extracted_text(meeting_text, sha, attachments_dir)

        # Synthetic "primary attachment" pointing at the saved corpus so the
        # __main__ orchestrator's incremental check on primary_sha keeps working.
        # KSBA's actual PDF attachments follow.
        corpus_attachment = Attachment(
            sha256=sha,
            url=meeting_url,
            mime="text/html",
            template_name="KSBA Meeting Page",
            extracted_text_path=f"data/attachments/{sha}.txt"
            if is_meaningful_text(meeting_text)
            else None,
        )

        meeting_id = f"ksba-{self.agency_id}-{row.public_meeting_id}"
        return Meeting(
            id=meeting_id,
            body_id=body.id,
            title=row.title or body.name,
            date=row.date,
            time=row.time,
            source_type="ksba",
            source_url=meeting_url,
            source_meeting_id=row.public_meeting_id,
            video_url=None,
            attachments=[corpus_attachment, *attachments],
            items=items,
        )


# ---------------------------------------------------------------- parsers

def _parse_us_datetime(s: str) -> tuple[str, str | None]:
    """Parse 'MM/DD/YYYY HH:MM AM/PM' -> ('YYYY-MM-DD', 'HH:MM' 24h or None)."""
    s = (s or "").strip()
    m = re.match(
        r"(\d{1,2})/(\d{1,2})/(\d{4})\s*(\d{1,2}):(\d{2})\s*([AP]M)?",
        s,
        re.IGNORECASE,
    )
    if not m:
        return "", None
    mm, dd, yyyy, hh, mi, ampm = m.groups()
    h = int(hh)
    if ampm and ampm.upper() == "PM" and h != 12:
        h += 12
    if ampm and ampm.upper() == "AM" and h == 12:
        h = 0
    iso = f"{int(yyyy):04d}-{int(mm):02d}-{int(dd):02d}"
    return iso, f"{h:02d}:{int(mi):02d}"


def _extract_agenda_items(soup: BeautifulSoup) -> list[AgendaItem]:
    """Parse outline-numbered items out of a KSBA meeting page.

    Items live in spans with the KSBA maroon (#990033). We don't rely on the
    inline style, just the outline-number text content + the fact that they're
    short title spans.
    """
    items: list[AgendaItem] = []
    seen: set[tuple[str, str]] = set()

    for span in soup.find_all("span"):
        if not isinstance(span, Tag):
            continue
        text = span.get_text(" ", strip=True)
        if not text or len(text) > 600:
            continue
        # Collapse whitespace so "III.A.\n  Recognition of..." → single line
        flat = re.sub(r"\s+", " ", text).strip()
        m = _OUTLINE_RE.match(flat)
        if not m:
            continue
        number, title = m.group(1), m.group(2).strip()
        if not title or title.lower() in {"vision statement"} and len(items) > 5:
            # cheap dedupe of sticky page-furniture spans
            pass
        key = (number, title[:80])
        if key in seen:
            continue
        seen.add(key)
        items.append(AgendaItem(item_number=number, file_number=None, title=title, section=None))

    return items


def _extract_attachments(soup: BeautifulSoup) -> list[Attachment]:
    out: list[Attachment] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=lambda h: h and "DisplayAttachment" in h):
        href = a.get("href")
        m = re.search(r"AttachmentID=(\d+)", href)
        if not m:
            continue
        aid = m.group(1)
        if aid in seen:
            continue
        seen.add(aid)
        url = urljoin(f"{KSBA_BASE}/", href)
        title = a.get_text(" ", strip=True)
        out.append(
            Attachment(
                sha256="",  # unknown until downloaded; Phase 1 doesn't fetch PDFs
                url=url,
                mime="application/pdf",
                template_name=title,
                extracted_text_path=None,
            )
        )
    return out


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
