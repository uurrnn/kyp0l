"""Data shapes for scraped Louisville Metro / Jefferson County agendas.

These are dataclasses, not pydantic models, to avoid an extra dep. JSON
on the way in/out is plain dicts; the `from_dict` / `to_dict` helpers do
shallow normalisation.
"""

from __future__ import annotations

import dataclasses as dc
import json
import re
from pathlib import Path
from typing import Any


def slugify(s: str) -> str:
    """Stable ASCII slug for filesystem paths and stable IDs."""
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


@dc.dataclass
class Body:
    id: str                 # our slug, e.g. "metro-council"
    name: str               # display name, e.g. "Metro Council"
    source_type: str        # "primegov" | "boarddocs"
    source_id: str          # upstream id, e.g. PrimeGov committeeId as str

    def to_dict(self) -> dict[str, Any]:
        return dc.asdict(self)


@dc.dataclass
class Attachment:
    """A single document attached to a meeting (typically the agenda PDF)."""

    sha256: str
    url: str                # presigned download URL at scrape time (volatile)
    mime: str               # "application/pdf", etc.
    template_name: str      # e.g. "Agenda", "Minutes"
    extracted_text_path: str | None = None   # repo-relative path or None

    def to_dict(self) -> dict[str, Any]:
        return dc.asdict(self)


@dc.dataclass
class AgendaItem:
    """One item parsed out of an agenda PDF (best-effort).

    For PrimeGov bodies that follow the "N. ID YY-NNNN <title>" pattern (Metro
    Council and committees), we get structured items. For others we fall back
    to one synthetic item that points at the full text.
    """

    item_number: str        # "1", "2", "Consent", "Communications-1", etc.
    file_number: str | None # e.g. "26-0030" if present
    title: str
    section: str | None = None   # "Consent Calendar", "Communications", etc.

    def to_dict(self) -> dict[str, Any]:
        return dc.asdict(self)


@dc.dataclass
class MemberVote:
    name: str
    option: str  # "yes" | "no" | "abstain" | "not voting"

    def to_dict(self) -> dict[str, Any]:
        return dc.asdict(self)


@dc.dataclass
class Vote:
    motion: str
    date: str
    chamber: str             # "lower" | "upper"
    result: str              # "pass" | "fail"
    counts: dict[str, int]   # {"yes": N, "no": N, "abstain": N, "not voting": N}
    member_votes: list[MemberVote]

    def to_dict(self) -> dict[str, Any]:
        return dc.asdict(self)


@dc.dataclass
class Sponsor:
    name: str
    party: str | None
    district: str | None
    primary: bool

    def to_dict(self) -> dict[str, Any]:
        return dc.asdict(self)


@dc.dataclass
class Action:
    date: str                       # ISO YYYY-MM-DD
    description: str
    chamber: str | None             # "lower" | "upper" | None
    classification: list[str]       # Open States action types

    def to_dict(self) -> dict[str, Any]:
        return dc.asdict(self)


@dc.dataclass
class Bill:
    id: str
    body_ids: list[str]
    session: str
    identifier: str
    title: str
    abstract: str | None
    classification: list[str]
    sponsors: list[Sponsor]
    actions: list[Action]
    votes: list[Vote]
    subjects: list[str]
    chamber_progress: dict[str, str | None]
    current_status: str
    last_action_date: str
    source_url: str
    openstates_id: str

    def to_dict(self) -> dict[str, Any]:
        return dc.asdict(self)


@dc.dataclass
class Meeting:
    id: str                       # e.g. "primegov-louisvilleky-9870"
    body_id: str                  # slug
    title: str                    # body name as printed on the agenda
    date: str                     # ISO YYYY-MM-DD
    time: str | None              # HH:MM (24h) or None
    source_type: str              # "primegov"
    source_url: str               # human-facing portal URL
    source_meeting_id: str        # upstream numeric id (str)
    video_url: str | None
    attachments: list[Attachment]
    items: list[AgendaItem]

    def to_dict(self) -> dict[str, Any]:
        d = dc.asdict(self)
        return d


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))
