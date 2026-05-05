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
    Person,
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


def slugify_person_name(name: str) -> str:
    """`First M. Last` → `first-m-last`. ASCII-only, hyphenated."""
    import re
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def person_slug_for_ky(name: str) -> str:
    """Build our canonical slug from an Open States full name."""
    return f"ky-{slugify_person_name(name)}" if name else ""


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
    # Open States exposes `latest_action_date` as a top-level convenience field
    # on bill responses; we prefer it because it can be slightly fresher than
    # the actions[] timeline during in-flight updates. Fall back to the latest
    # parsed action when absent (e.g. minimal/test fixtures).
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
    # Open States returns party at person.party; current_role.party tends to be empty for KY.
    party = person.get("party") or role.get("party") or s.get("party")
    district = role.get("district") or s.get("district")
    return Sponsor(
        name=s.get("name") or person.get("name") or "",
        party=party,
        district=str(district) if district is not None else None,
        primary=bool(s.get("primary")),
        person_id=person.get("id") or None,
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
                person_id=voter.get("id") or None,
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


def parse_person(raw: dict[str, Any]) -> Person | None:
    """Convert one Open States `/people` entry into our Person.

    Returns None if the entry has no current legislative role we recognise.
    """
    role = raw.get("current_role") or {}
    chamber = role.get("org_classification")
    if chamber not in _CHAMBER_TO_BODY:
        return None
    body_id = _CHAMBER_TO_BODY[chamber]

    name = raw.get("name") or ""
    if not name:
        return None

    offices = raw.get("offices") or []
    contact: dict[str, Any] = {
        "addresses": [],
        "phones": [],
        "emails": [],
        "links": [],
    }
    for off in offices:
        if off.get("address"):
            contact["addresses"].append({
                "classification": off.get("classification") or "",
                "address": off.get("address"),
            })
        if off.get("voice"):
            contact["phones"].append({
                "classification": off.get("classification") or "",
                "voice": off.get("voice"),
            })
        if off.get("email"):
            contact["emails"].append(off.get("email"))
    if raw.get("email"):
        contact["emails"].append(raw["email"])
    # Dedup emails
    contact["emails"] = list(dict.fromkeys(contact["emails"]))

    sources = []
    for src in raw.get("sources") or []:
        url = src.get("url") if isinstance(src, dict) else None
        if url:
            sources.append(url)
    if raw.get("openstates_url"):
        sources.append(raw["openstates_url"])

    district = role.get("district")

    return Person(
        id=person_slug_for_ky(name),
        source="openstates",
        source_id=raw.get("id") or "",
        name=name,
        body_id=body_id,
        chamber=chamber,
        party=raw.get("party") or None,
        district=str(district) if district is not None else None,
        active=True,
        photo_url=(raw.get("image") or None),
        contact=contact,
        sources=sources,
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
        # Last X-RateLimit-Remaining we observed; None until the first call.
        # Useful for callers to peek before doing expensive paginated work.
        self.last_remaining: int | None = None
        self._announced_thresholds: set[int] = set()

    def _record_quota(self, r: requests.Response) -> None:
        """Update last_remaining and announce when crossing thresholds."""
        rem_str = r.headers.get("X-RateLimit-Remaining")
        if rem_str is None:
            return
        try:
            remaining = int(rem_str)
        except ValueError:
            return
        self.last_remaining = remaining
        for threshold in (500, 100, 50, 20, 5):
            if remaining <= threshold and threshold not in self._announced_thresholds:
                self._announced_thresholds.add(threshold)
                print(f"  [openstates] quota remaining: {remaining}")
                break

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        """GET with retries + courtesy throttle.

        Retries up to 4 attempts total on:
          - 429 Too Many Requests (free-tier per-minute burst limit)
          - 5xx server errors
          - ReadTimeout / ConnectionError (transient network blips)
        Backoff escalates: 30s, 90s, 240s. For 429s, honors Retry-After
        if it's larger than the scheduled backoff. Other 4xx errors fail
        immediately — they're our bugs, not transient.
        """
        url = f"{BASE_URL}{path}"
        backoffs = [30, 90, 240]  # waits before attempts 2, 3, 4
        max_attempts = 4

        r = None
        for attempt in range(1, max_attempts + 1):
            is_last = attempt == max_attempts
            try:
                r = self.session.get(url, params=params, timeout=30)
            except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
                if is_last:
                    raise
                wait = backoffs[attempt - 1]
                print(f"  [openstates] {type(e).__name__}; sleeping {wait}s before retry {attempt + 1}/{max_attempts}")
                time.sleep(wait)
                continue

            if r.status_code == 429:
                ra = r.headers.get("Retry-After") or "?"
                rem = r.headers.get("X-RateLimit-Remaining") or "?"
                lim = r.headers.get("X-RateLimit-Limit") or "?"
                if is_last:
                    print(f"  [openstates] 429 (remaining={rem}/{lim}, retry-after={ra}); giving up")
                    r.raise_for_status()
                wait = max(int(r.headers.get("Retry-After") or 0), backoffs[attempt - 1])
                print(f"  [openstates] 429 (remaining={rem}/{lim}, retry-after={ra}); sleeping {wait}s before retry {attempt + 1}/{max_attempts}")
                time.sleep(wait)
                continue

            if 500 <= r.status_code < 600:
                if is_last:
                    r.raise_for_status()
                wait = backoffs[attempt - 1]
                print(f"  [openstates] {r.status_code}; sleeping {wait}s before retry {attempt + 1}/{max_attempts}")
                time.sleep(wait)
                continue

            r.raise_for_status()  # raises immediately on 4xx other than 429
            break

        assert r is not None
        self._record_quota(r)
        remaining = int(r.headers.get("X-RateLimit-Remaining", "1000"))
        if remaining < 50:
            time.sleep(60)
        else:
            time.sleep(1.0)
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

    def list_people(self) -> Iterator[dict[str, Any]]:
        """Paginate `GET /people?jurisdiction=ky&include=offices`.

        ~138 KY legislators total → ~3 pages at per_page=50.
        """
        page = 1
        per_page = 50
        while True:
            data = self._get(
                "/people",
                jurisdiction=self.jurisdiction,
                include=["offices"],
                page=page,
                per_page=per_page,
            )
            results = data.get("results") or []
            for p in results:
                yield p
            pagination = data.get("pagination") or {}
            if page >= int(pagination.get("max_page") or 1):
                return
            page += 1

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
