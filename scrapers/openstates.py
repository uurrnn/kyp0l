"""Open States API v3 adapter.

Pulls Kentucky General Assembly bills (and committee events, if available) into
the existing tracker shape. Bills become a new top-level entity (data/bills/);
events would reuse the Meeting model (data/meetings/<lazy-body>/) — events are
deferred for KY in Phase 3 because Open States returns ~1 event for the
jurisdiction, which is too thin to be useful.

Endpoints used (https://docs.openstates.org/api-v3/):
    GET /jurisdictions/{jurisdiction}?include=legislative_sessions
    GET /bills?jurisdiction=...&session=...&include=...

Auth: header X-API-KEY = $OPENSTATES_API_KEY. Empty/missing key -> caller skips.
"""

from __future__ import annotations

import time
from typing import Any, Iterator

import requests

from scrapers.models import (
    Action,
    Bill,
    MemberVote,
    Sponsor,
    Vote,
    chamber_progress_to_status,
    derive_chamber_progress,
)


BASE_URL = "https://v3.openstates.org"
USER_AGENT = "louisville-politics-tracker (+https://github.com/uurrnn/kyp0l)"

_CHAMBER_TO_BODY = {
    "lower": "ky-house",
    "upper": "ky-senate",
}


def parse_bill(raw: dict[str, Any], session: str) -> Bill:
    """Convert one Open States bill dict into our Bill dataclass."""
    actions = [_parse_action(a) for a in raw.get("actions", []) or []]
    chamber_progress = derive_chamber_progress(actions)

    sponsors = [_parse_sponsor(s) for s in raw.get("sponsorships", []) or []]
    votes = [_parse_vote(v) for v in (raw.get("votes") or raw.get("vote_events") or [])]

    abstracts = raw.get("abstracts") or []
    abstract = abstracts[0].get("abstract") if abstracts else None

    subjects = raw.get("subject") or []  # Open States returns "subject" as list[str]

    body_ids = _body_ids_for(raw, actions)
    last_action_date = (
        raw.get("latest_action_date")
        or max((a.date for a in actions if a.date), default="")
    )[:10]

    sources = raw.get("sources") or []
    source_url = sources[0].get("url", "") if sources else ""

    identifier = raw["identifier"]
    bill_slug = identifier.lower().replace(" ", "")

    return Bill(
        id=f"openstates-ky-{session}-{bill_slug}",
        body_ids=body_ids,
        session=session,
        identifier=identifier,
        title=raw.get("title") or "",
        abstract=abstract,
        classification=raw.get("classification") or [],
        sponsors=sponsors,
        actions=actions,
        votes=votes,
        subjects=subjects,
        chamber_progress=chamber_progress,
        current_status=chamber_progress_to_status(chamber_progress),
        last_action_date=last_action_date,
        source_url=source_url,
        openstates_id=raw["id"],
    )


def _parse_action(a: dict[str, Any]) -> Action:
    org = a.get("organization") or {}
    chamber = org.get("classification") or a.get("chamber")
    return Action(
        date=(a.get("date") or "")[:10],
        description=a.get("description") or "",
        chamber=chamber if chamber in ("lower", "upper") else None,
        classification=a.get("classification") or [],
    )


def _parse_sponsor(s: dict[str, Any]) -> Sponsor:
    person = s.get("person") or {}
    role = person.get("current_role") or {}
    party = role.get("party") or s.get("party")
    district = role.get("district") or s.get("district")
    return Sponsor(
        name=s.get("name") or person.get("name") or "",
        party=party,
        district=str(district) if district is not None else None,
        primary=bool(s.get("primary")),
    )


def _parse_vote(v: dict[str, Any]) -> Vote:
    org = v.get("organization") or {}
    chamber = org.get("classification") or v.get("chamber") or "lower"
    if chamber not in ("lower", "upper"):
        chamber = "lower"

    counts = {"yes": 0, "no": 0, "abstain": 0, "not voting": 0}
    for c in v.get("counts") or []:
        opt = c.get("option") or ""
        val = int(c.get("value") or 0)
        if opt in counts:
            counts[opt] = val

    member_votes: list[MemberVote] = []
    for vv in v.get("votes") or []:
        voter = vv.get("voter") or {}
        member_votes.append(
            MemberVote(
                name=vv.get("voter_name") or voter.get("name") or "",
                option=vv.get("option") or "",
            )
        )

    motion = v.get("motion_text")
    if not motion:
        mcs = v.get("motion_classification") or []
        motion = mcs[0] if mcs else ""

    return Vote(
        motion=motion,
        date=(v.get("start_date") or v.get("date") or "")[:10],
        chamber=chamber,
        result=v.get("result") or "",
        counts=counts,
        member_votes=member_votes,
    )


def _body_ids_for(raw: dict[str, Any], actions: list[Action]) -> list[str]:
    """Always include chamber of origin; add other chamber once it's seen."""
    origin = (raw.get("from_organization") or {}).get("classification")
    seen: set[str] = set()
    if origin in _CHAMBER_TO_BODY:
        seen.add(_CHAMBER_TO_BODY[origin])
    for a in actions:
        if a.chamber in _CHAMBER_TO_BODY:
            seen.add(_CHAMBER_TO_BODY[a.chamber])
    if not seen:
        ident = (raw.get("identifier") or "").upper()
        if ident.startswith(("HB", "HR", "HCR", "HJR")):
            seen.add("ky-house")
        elif ident.startswith(("SB", "SR", "SCR", "SJR")):
            seen.add("ky-senate")
    out: list[str] = []
    if "ky-house" in seen:
        out.append("ky-house")
    if "ky-senate" in seen:
        out.append("ky-senate")
    return out


class OpenStatesScraper:
    """Stateful HTTP client for Open States v3."""

    def __init__(self, api_key: str, jurisdiction: str = "ky") -> None:
        if not api_key:
            raise ValueError("OPENSTATES_API_KEY is required")
        self.api_key = api_key
        self.jurisdiction = jurisdiction
        self.session = requests.Session()
        self.session.headers.update({
            "X-API-KEY": api_key,
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        r = self.session.get(url, params=params, timeout=30)
        r.raise_for_status()
        remaining = int(r.headers.get("X-RateLimit-Remaining", "1000"))
        if remaining < 50:
            time.sleep(60)
        return r.json()

    def current_session(self) -> str:
        data = self._get(
            f"/jurisdictions/{self.jurisdiction}",
            include="legislative_sessions",
        )
        sessions = data.get("legislative_sessions") or []
        active = [s for s in sessions if s.get("active")]
        if active:
            return active[0]["identifier"]
        sessions.sort(key=lambda s: s.get("start_date") or "", reverse=True)
        if sessions:
            return sessions[0]["identifier"]
        raise RuntimeError(f"no legislative sessions found for {self.jurisdiction!r}")

    def list_bills(self, session: str) -> Iterator[dict[str, Any]]:
        page = 1
        per_page = 20
        while True:
            data = self._get(
                "/bills",
                jurisdiction=self.jurisdiction,
                session=session,
                include=["sponsorships", "actions", "votes", "abstracts"],
                page=page,
                per_page=per_page,
            )
            results = data.get("results") or []
            for b in results:
                yield b
            pagination = data.get("pagination") or {}
            if page >= int(pagination.get("max_page") or 1):
                return
            page += 1
