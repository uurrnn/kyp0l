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
    person_id: str | None = None  # upstream id (e.g. "ocd-person/...") if known

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
    person_id: str | None = None  # upstream id (e.g. "ocd-person/...") if known

    def to_dict(self) -> dict[str, Any]:
        return dc.asdict(self)


@dc.dataclass
class Person:
    """An elected official we can link bills/votes back to."""

    id: str                       # our slug, stable per session, e.g. "ky-wheeler-phillip"
    source: str                   # "openstates" | "metro-council"
    source_id: str                # "ocd-person/<uuid>" or our own id for hand-curated
    name: str
    body_id: str                  # "ky-house" | "ky-senate" | "metro-council"
    chamber: str | None           # "lower" | "upper" | None
    party: str | None
    district: str | None
    active: bool
    photo_url: str | None
    contact: dict[str, Any]       # {email, phone, addresses[], links[]}
    sources: list[str]            # upstream URLs to canonical bio pages

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


# Order matters: later items override earlier ones unless the new state is
# weaker (we never downgrade — see _PROGRESS_RANK).
_PROGRESS_RANK = {
    None: 0,
    "introduced": 1,
    "in_committee": 2,
    "passed_committee": 3,
    "passed": 4,
    "failed": 4,  # terminal, same rank as passed so it can't be overridden
}


def _classify_chamber_action(classification: list[str]) -> str | None:
    cs = set(classification or [])
    if "passage" in cs:
        return "passed"
    if "failure" in cs:
        return "failed"
    if any(c.startswith("committee-passage") for c in cs):
        return "passed_committee"
    if "referral-committee" in cs:
        return "in_committee"
    if "introduction" in cs:
        return "introduced"
    return None


def _classify_governor_action(classification: list[str]) -> str | None:
    cs = set(classification or [])
    if "executive-signature" in cs:
        return "signed"
    if "executive-veto" in cs:
        return "vetoed"
    return None


def derive_chamber_progress(actions: list[Action]) -> dict[str, str | None]:
    """Walk an action timeline and return the most-progressed state per chamber.

    Progress is monotonic: once a chamber reaches 'passed' or 'failed' it can
    not be downgraded by later actions (e.g. recommittal).
    """
    progress: dict[str, str | None] = {"lower": None, "upper": None, "governor": None}

    for action in actions:
        gov_state = _classify_governor_action(action.classification)
        if gov_state is not None:
            progress["governor"] = gov_state
            continue

        chamber = action.chamber
        if chamber not in ("lower", "upper"):
            continue
        new_state = _classify_chamber_action(action.classification)
        if new_state is None:
            continue
        if _PROGRESS_RANK[new_state] >= _PROGRESS_RANK[progress[chamber]]:
            progress[chamber] = new_state

    return progress


_CHAMBER_LABEL = {"lower": "House", "upper": "Senate"}
_STATE_VERB = {
    "introduced": "Introduced",
    "in_committee": "in committee",
    "passed_committee": "passed committee",
    "passed": "Passed",
    "failed": "Failed",
}


def _in_chamber_phrase(state: str, chamber_label: str) -> str:
    """Render the 'still in <chamber>' clause of a status string idiomatically."""
    if state == "in_committee":
        return f"in {chamber_label} committee"
    if state == "passed_committee":
        return f"out of {chamber_label} committee"
    if state == "introduced":
        return f"in {chamber_label}"
    return f"{_STATE_VERB[state]} {chamber_label}"


def chamber_progress_to_status(cp: dict[str, str | None]) -> str:
    """Render a chamber_progress dict as a one-line human summary."""
    if cp.get("governor") == "signed":
        return "Signed by governor"
    if cp.get("governor") == "vetoed":
        return "Vetoed by governor"

    lower = cp.get("lower")
    upper = cp.get("upper")

    if lower == "passed" and upper == "passed":
        return "Passed House and Senate"
    if lower == "passed" and upper in (None, "introduced"):
        return "Passed House, in Senate" if upper == "introduced" else "Passed House"
    if upper == "passed" and lower in (None, "introduced"):
        return "Passed Senate, in House" if lower == "introduced" else "Passed Senate"
    if lower == "passed" and upper:
        return f"Passed House, {_in_chamber_phrase(upper, 'Senate')}"
    if upper == "passed" and lower:
        return f"Passed Senate, {_in_chamber_phrase(lower, 'House')}"

    if lower == "failed":
        return "Failed in House"
    if upper == "failed":
        return "Failed in Senate"
    if lower == "in_committee" and not upper:
        return "In House committee"
    if upper == "in_committee" and not lower:
        return "In Senate committee"
    if lower == "introduced" and not upper:
        return "Introduced in House"
    if upper == "introduced" and not lower:
        return "Introduced in Senate"

    parts = []
    for ch in ("lower", "upper"):
        s = cp.get(ch)
        if s:
            parts.append(f"{_STATE_VERB[s]} {_CHAMBER_LABEL[ch]}")
    return " · ".join(parts) or "Status unknown"


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))
