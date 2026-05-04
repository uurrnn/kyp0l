"""Capture Open States fixture data for tests.

Hits the live API once, dumps representative bills + events to
tests/fixtures/. Do NOT commit the API key; read it from env.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

BASE = "https://v3.openstates.org"
JURISDICTION = "ky"
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def get(path: str, **params) -> dict:
    api_key = os.environ.get("OPENSTATES_API_KEY")
    if not api_key:
        print("ERROR: OPENSTATES_API_KEY is not set in env")
        sys.exit(2)
    headers = {"X-API-KEY": api_key, "Accept": "application/json"}
    r = requests.get(f"{BASE}{path}", params=params, headers=headers, timeout=30)
    print(f"  GET {path}  -> {r.status_code}  X-RateLimit-Remaining={r.headers.get('X-RateLimit-Remaining')}")
    if r.status_code != 200:
        print("  body:", r.text[:500])
    r.raise_for_status()
    return r.json()


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)

    sessions = get(f"/jurisdictions/{JURISDICTION}", include="legislative_sessions")
    (FIXTURES / "openstates_session.json").write_text(
        json.dumps(sessions, indent=2), encoding="utf-8"
    )
    legislative_sessions = sessions.get("legislative_sessions", [])
    active = next(
        (s for s in legislative_sessions if s.get("active")),
        None,
    )
    if active is None:
        # Pick the most recent session if no active one is flagged
        legislative_sessions.sort(key=lambda s: s.get("start_date") or "", reverse=True)
        active = legislative_sessions[0] if legislative_sessions else None
    if active is None:
        print("ERROR: no legislative sessions returned")
        return 3
    print(f"Active session: {active['identifier']}")

    bills = get(
        "/bills",
        jurisdiction=JURISDICTION,
        session=active["identifier"],
        include=["sponsorships", "actions", "votes", "abstracts"],
        per_page=20,
    )
    results = bills.get("results") or []
    if not results:
        print("ERROR: no bills returned for active session")
        return 4

    introduced = next(
        (
            b for b in results
            if all("passage" not in (a.get("classification") or []) for a in b.get("actions", []) or [])
        ),
        results[0],
    )
    passed_house = next(
        (
            b for b in results
            if any("passage" in (a.get("classification") or []) for a in b.get("actions", []) or [])
        ),
        results[-1],
    )

    (FIXTURES / "openstates_bill_introduced.json").write_text(
        json.dumps(introduced, indent=2), encoding="utf-8"
    )
    (FIXTURES / "openstates_bill_passed_house.json").write_text(
        json.dumps(passed_house, indent=2), encoding="utf-8"
    )
    print(f"  introduced: {introduced.get('identifier')}")
    print(f"  passed:     {passed_house.get('identifier')}")

    events = get(
        "/events",
        jurisdiction=JURISDICTION,
        include=["agenda", "related_entities"],
        per_page=10,
    )
    event_results = events.get("results") or []
    if event_results:
        (FIXTURES / "openstates_event.json").write_text(
            json.dumps(event_results[0], indent=2), encoding="utf-8"
        )
        print(f"Captured 1 event fixture (total available: {len(event_results)})")
    else:
        print("No events returned for KY in active session — events deferred to Phase 3.5.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
