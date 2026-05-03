# Kentucky State Legislature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Kentucky General Assembly bills + committee events + roll-call votes to the existing tracker, sourced from the Open States API, and surface them on the static dashboard alongside the existing local-government data.

**Architecture:** New `Bill` entity stored in `data/bills/<session>/<bill>.json`, parallel to the existing `Meeting` entity. Bills have `body_ids: list[str]` so they appear under both KY chambers once they cross over. Floor votes nest inside each bill's `votes[]`. Committee meetings reuse the existing `Meeting` model via Open States `/events`. Site adds `/bill/[id]` and `/bills` routes plus updates to `/body/[id]` and `/`. Pagefind indexes bills as a new searchable corpus. Workflow gains `OPENSTATES_API_KEY` from a GitHub repo secret; missing key cleanly skips the source.

**Tech Stack:** Python 3.14 + `requests` + `pytest` (new for this project); Open States REST API v3; Astro 5 + Pagefind for the site; existing `scrapers/models.py` dataclass patterns for the new entity.

---

## File Structure

**Created:**
- `tests/__init__.py` — empty marker
- `tests/conftest.py` — pytest config + fixture dir paths
- `tests/test_chamber_progress.py` — unit tests for action-timeline → chamber_progress
- `tests/test_current_status.py` — unit tests for chamber_progress → human string
- `tests/test_openstates_parsing.py` — unit tests for raw API dict → `Bill`
- `tests/fixtures/openstates_bill_passed_house.json` — captured live response
- `tests/fixtures/openstates_bill_introduced.json` — captured live response
- `tests/fixtures/openstates_event.json` — captured live response (or none, if events are thin)
- `tests/fixtures/openstates_session.json` — captured live response for jurisdictions endpoint
- `scrapers/openstates.py` — Open States adapter (analog of `scrapers/primegov.py`)
- `site/src/pages/bill/[id].astro` — bill detail page
- `site/src/pages/bills.astro` — bills index with client-side filters
- `pytest.ini` — minimal pytest config

**Modified:**
- `scrapers/models.py` — add `Bill`, `Sponsor`, `Action`, `Vote`, `MemberVote` dataclasses + `derive_chamber_progress()` + `chamber_progress_to_status()`
- `scrapers/__main__.py` — third source path (`run_openstates`), graceful skip on missing API key
- `site/src/lib/data.ts` — add `Bill`-shaped TypeScript interfaces + `getBills`, `getBillById`, `getBillsByBody`, `getRecentBills`
- `site/src/layouts/Layout.astro` — brand → "Kentucky + Louisville Politics"
- `site/src/pages/index.astro` — add "Recent legislative activity" section
- `site/src/pages/body/[id].astro` — add "Bills" section beneath "Meetings"
- `.github/workflows/scrape-build-deploy.yml` — pass `OPENSTATES_API_KEY` env var into the scrape step

Each scraper file stays under ~400 lines and owns exactly one upstream source. Each site page has one route. Tests live under `tests/` mirroring the source layout.

---

### Task 0: Bootstrap pytest

**Files:**
- Create: `pytest.ini`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Add pytest config**

Create `pytest.ini`:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
addopts = -ra -q
```

- [ ] **Step 2: Add empty package marker + conftest**

Create `tests/__init__.py` empty.

Create `tests/conftest.py`:

```python
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR
```

- [ ] **Step 3: Write a smoke test**

Create `tests/test_smoke.py`:

```python
def test_python_works():
    assert 1 + 1 == 2
```

- [ ] **Step 4: Run tests to verify harness**

Run: `.venv/Scripts/python.exe -m pytest -v`

Expected: 1 passed in ~0.05s.

- [ ] **Step 5: Commit**

```bash
git add pytest.ini tests/
git commit -m "Bootstrap pytest"
```

---

### Task 1: Capture Open States fixture data

**Why this task before TDD:** test fixtures must be based on real API responses, not on what we *think* the API returns. This task probes Open States once to capture realistic JSON, then later tests use those fixtures.

**Prereq:** the user has obtained an API key from openstates.org and exported `OPENSTATES_API_KEY=<key>` in the shell.

**Files:**
- Create: `scratch/probe_openstates.py`
- Create: `tests/fixtures/openstates_session.json`
- Create: `tests/fixtures/openstates_bill_introduced.json`
- Create: `tests/fixtures/openstates_bill_passed_house.json`
- Create: `tests/fixtures/openstates_event.json` (or skip if events are empty)

- [ ] **Step 1: Write the probe**

Create `scratch/probe_openstates.py`:

```python
"""Capture Open States fixture data for tests.

Hits the live API once, dumps three representative bills + events to
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
    r.raise_for_status()
    return r.json()


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)

    sessions = get(f"/jurisdictions/{JURISDICTION}", include="legislative_sessions")
    (FIXTURES / "openstates_session.json").write_text(
        json.dumps(sessions, indent=2), encoding="utf-8"
    )
    active = next(
        s for s in sessions["legislative_sessions"] if s.get("active")
    )
    print(f"Active session: {active['identifier']}")

    bills = get(
        "/bills",
        jurisdiction=JURISDICTION,
        session=active["identifier"],
        include=["sponsorships", "actions", "votes", "abstracts"],
        per_page=20,
    )
    introduced = next(
        b for b in bills["results"]
        if all(a["classification"] != ["passage"] for a in b.get("actions", []))
    )
    passed_house = next(
        (
            b for b in bills["results"]
            if any("passage" in (a.get("classification") or []) for a in b.get("actions", []))
        ),
        bills["results"][0],
    )

    (FIXTURES / "openstates_bill_introduced.json").write_text(
        json.dumps(introduced, indent=2), encoding="utf-8"
    )
    (FIXTURES / "openstates_bill_passed_house.json").write_text(
        json.dumps(passed_house, indent=2), encoding="utf-8"
    )

    events = get(
        "/events",
        jurisdiction=JURISDICTION,
        include=["agenda", "related_entities"],
        per_page=10,
    )
    if events.get("results"):
        (FIXTURES / "openstates_event.json").write_text(
            json.dumps(events["results"][0], indent=2), encoding="utf-8"
        )
        print(f"Captured 1 event fixture (total available: {len(events['results'])})")
    else:
        print("No events returned for KY in active session — events deferred to Phase 3.5.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the probe**

Run:

```bash
OPENSTATES_API_KEY=<key> .venv/Scripts/python.exe scratch/probe_openstates.py
```

Expected output: three files written under `tests/fixtures/`, plus `openstates_event.json` if KY has events. Sample log:

```
  GET /jurisdictions/ky  -> 200  X-RateLimit-Remaining=9999
Active session: 2026rs
  GET /bills  -> 200  X-RateLimit-Remaining=9998
  GET /events  -> 200  X-RateLimit-Remaining=9997
Captured 1 event fixture (total available: 7)
```

- [ ] **Step 3: Inspect the fixtures**

Run:

```bash
.venv/Scripts/python.exe -c "import json; d = json.load(open('tests/fixtures/openstates_bill_introduced.json')); print(sorted(d.keys())); print('actions:', len(d.get('actions', [])))"
```

Expected: a list of top-level keys including `id`, `identifier`, `title`, `actions`, `sponsorships`, `votes` (or `vote_events`), `abstracts`, `subject`, `from_organization`, `updated_at`.

If the actual key names differ from what the spec assumed (e.g. `sponsorships` vs `sponsors`, `vote_events` vs `votes`), record the real names — later tasks must use them.

- [ ] **Step 4: Commit**

```bash
git add scratch/probe_openstates.py tests/fixtures/
git commit -m "Capture Open States fixture data for tests"
```

---

### Task 2: Add Bill / Sponsor / Action / Vote / MemberVote dataclasses

**Files:**
- Modify: `scrapers/models.py` (append, do not delete existing)
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_models.py`:

```python
from scrapers.models import (
    Action,
    Bill,
    MemberVote,
    Sponsor,
    Vote,
)


def test_bill_round_trip_to_dict():
    bill = Bill(
        id="openstates-ky-2026rs-hb15",
        body_ids=["ky-house"],
        session="2026rs",
        identifier="HB 15",
        title="An Act relating to public records",
        abstract="A summary of HB 15.",
        classification=["bill"],
        sponsors=[
            Sponsor(name="Rep. Smith", party="R", district="1", primary=True),
        ],
        actions=[
            Action(
                date="2026-01-08",
                description="introduced in House",
                chamber="lower",
                classification=["introduction"],
            ),
        ],
        votes=[
            Vote(
                motion="Third reading",
                date="2026-02-15",
                chamber="lower",
                result="pass",
                counts={"yes": 60, "no": 40, "abstain": 0, "not voting": 0},
                member_votes=[
                    MemberVote(name="Rep. Smith", option="yes"),
                ],
            ),
        ],
        subjects=["Government Operations"],
        chamber_progress={"lower": "passed", "upper": None, "governor": None},
        current_status="Passed House",
        last_action_date="2026-02-15",
        source_url="https://apps.legislature.ky.gov/record/26rs/hb15.html",
        openstates_id="ocd-bill/0000-0000-0000-0000",
    )

    d = bill.to_dict()

    assert d["id"] == "openstates-ky-2026rs-hb15"
    assert d["body_ids"] == ["ky-house"]
    assert d["sponsors"][0]["name"] == "Rep. Smith"
    assert d["actions"][0]["classification"] == ["introduction"]
    assert d["votes"][0]["counts"]["yes"] == 60
    assert d["votes"][0]["member_votes"][0]["option"] == "yes"
    assert d["chamber_progress"] == {"lower": "passed", "upper": None, "governor": None}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_models.py -v`

Expected: ImportError or AttributeError — `Bill`, `Sponsor`, etc. don't exist yet.

- [ ] **Step 3: Add the dataclasses**

Edit `scrapers/models.py`. After the existing `AgendaItem` and before `Meeting`, add:

```python
@dataclass
class MemberVote:
    name: str
    option: str  # "yes" | "no" | "abstain" | "not voting"

    def to_dict(self) -> dict[str, Any]:
        return dc.asdict(self)


@dataclass
class Vote:
    motion: str
    date: str
    chamber: str             # "lower" | "upper"
    result: str              # "pass" | "fail"
    counts: dict[str, int]   # {"yes": N, "no": N, "abstain": N, "not voting": N}
    member_votes: list[MemberVote]

    def to_dict(self) -> dict[str, Any]:
        return dc.asdict(self)


@dataclass
class Sponsor:
    name: str
    party: str | None
    district: str | None
    primary: bool

    def to_dict(self) -> dict[str, Any]:
        return dc.asdict(self)


@dataclass
class Action:
    date: str                       # ISO YYYY-MM-DD
    description: str
    chamber: str | None             # "lower" | "upper" | None
    classification: list[str]       # Open States action types

    def to_dict(self) -> dict[str, Any]:
        return dc.asdict(self)


@dataclass
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
        d = dc.asdict(self)
        return d
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_models.py -v`

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add scrapers/models.py tests/test_models.py
git commit -m "Add Bill / Sponsor / Action / Vote / MemberVote dataclasses"
```

---

### Task 3: Chamber-progress derivation

**Files:**
- Modify: `scrapers/models.py` (add `derive_chamber_progress` function)
- Test: `tests/test_chamber_progress.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_chamber_progress.py`:

```python
from scrapers.models import Action, derive_chamber_progress


def _action(classification, chamber="lower", date="2026-01-01"):
    return Action(date=date, description="", chamber=chamber, classification=classification)


def test_introduced_only():
    actions = [_action(["introduction"])]
    assert derive_chamber_progress(actions) == {
        "lower": "introduced",
        "upper": None,
        "governor": None,
    }


def test_referred_to_committee():
    actions = [
        _action(["introduction"]),
        _action(["referral-committee"]),
    ]
    assert derive_chamber_progress(actions)["lower"] == "in_committee"


def test_committee_passage():
    actions = [
        _action(["introduction"]),
        _action(["committee-passage-favorable"]),
    ]
    assert derive_chamber_progress(actions)["lower"] == "passed_committee"


def test_passed_lower_then_referred_upper():
    actions = [
        _action(["introduction"], chamber="lower"),
        _action(["passage"], chamber="lower"),
        _action(["referral-committee"], chamber="upper"),
    ]
    cp = derive_chamber_progress(actions)
    assert cp["lower"] == "passed"
    assert cp["upper"] == "in_committee"


def test_governor_signature():
    actions = [
        _action(["passage"], chamber="lower"),
        _action(["passage"], chamber="upper"),
        _action(["executive-signature"], chamber=None),
    ]
    cp = derive_chamber_progress(actions)
    assert cp["lower"] == "passed"
    assert cp["upper"] == "passed"
    assert cp["governor"] == "signed"


def test_governor_veto():
    actions = [
        _action(["passage"], chamber="lower"),
        _action(["passage"], chamber="upper"),
        _action(["executive-veto"], chamber=None),
    ]
    assert derive_chamber_progress(actions)["governor"] == "vetoed"


def test_progress_is_monotonic():
    """A later recommittal must not downgrade 'passed' back to 'in_committee'."""
    actions = [
        _action(["passage"], chamber="lower"),
        _action(["referral-committee"], chamber="lower"),  # recommit
    ]
    assert derive_chamber_progress(actions)["lower"] == "passed"


def test_failure_recorded():
    actions = [
        _action(["introduction"]),
        _action(["failure"]),
    ]
    assert derive_chamber_progress(actions)["lower"] == "failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_chamber_progress.py -v`

Expected: ImportError on `derive_chamber_progress`.

- [ ] **Step 3: Implement `derive_chamber_progress`**

Append to `scrapers/models.py`:

```python
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
    """Map an Open States action classification to a chamber state, or None."""
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


def derive_chamber_progress(actions: list["Action"]) -> dict[str, str | None]:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_chamber_progress.py -v`

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add scrapers/models.py tests/test_chamber_progress.py
git commit -m "Add derive_chamber_progress() with monotonic progression"
```

---

### Task 4: Human-readable `current_status`

**Files:**
- Modify: `scrapers/models.py` (add `chamber_progress_to_status`)
- Test: `tests/test_current_status.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_current_status.py`:

```python
from scrapers.models import chamber_progress_to_status


def test_signed_by_governor():
    cp = {"lower": "passed", "upper": "passed", "governor": "signed"}
    assert chamber_progress_to_status(cp) == "Signed by governor"


def test_vetoed():
    cp = {"lower": "passed", "upper": "passed", "governor": "vetoed"}
    assert chamber_progress_to_status(cp) == "Vetoed by governor"


def test_passed_house_in_senate_committee():
    cp = {"lower": "passed", "upper": "in_committee", "governor": None}
    assert chamber_progress_to_status(cp) == "Passed House, in Senate committee"


def test_introduced_in_house():
    cp = {"lower": "introduced", "upper": None, "governor": None}
    assert chamber_progress_to_status(cp) == "Introduced in House"


def test_introduced_in_senate():
    cp = {"lower": None, "upper": "introduced", "governor": None}
    assert chamber_progress_to_status(cp) == "Introduced in Senate"


def test_passed_both_chambers_pending_governor():
    cp = {"lower": "passed", "upper": "passed", "governor": None}
    assert chamber_progress_to_status(cp) == "Passed House and Senate"


def test_failed_in_house():
    cp = {"lower": "failed", "upper": None, "governor": None}
    assert chamber_progress_to_status(cp) == "Failed in House"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_current_status.py -v`

Expected: ImportError.

- [ ] **Step 3: Implement `chamber_progress_to_status`**

Append to `scrapers/models.py`:

```python
_CHAMBER_LABEL = {"lower": "House", "upper": "Senate"}
_STATE_VERB = {
    "introduced": "Introduced",
    "in_committee": "in committee",
    "passed_committee": "passed committee",
    "passed": "Passed",
    "failed": "Failed",
}


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
        return f"Passed House, {_STATE_VERB[upper]} Senate" if upper != "passed" else "Passed House and Senate"
    if upper == "passed" and lower:
        return f"Passed Senate, {_STATE_VERB[lower]} House" if lower != "passed" else "Passed House and Senate"

    # Single-chamber, no passage yet
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

    # Fallback for any unhandled mix
    parts = []
    for ch in ("lower", "upper"):
        s = cp.get(ch)
        if s:
            parts.append(f"{_STATE_VERB[s]} {_CHAMBER_LABEL[ch]}")
    return " · ".join(parts) or "Status unknown"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_current_status.py -v`

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add scrapers/models.py tests/test_current_status.py
git commit -m "Add chamber_progress_to_status() one-line renderer"
```

---

### Task 5: Open States bill parser (raw dict → Bill)

**Files:**
- Create: `scrapers/openstates.py`
- Test: `tests/test_openstates_parsing.py`

This task assumes Task 1's fixtures exist. If a fixture key is named differently in the live data than what these tests expect (e.g. `sponsorships` vs `sponsors`), update the tests to match the captured fixture and adjust the parser accordingly.

- [ ] **Step 1: Write the failing test**

Create `tests/test_openstates_parsing.py`:

```python
import json

from scrapers.openstates import parse_bill


def test_parse_introduced_bill(fixtures_dir):
    raw = json.loads((fixtures_dir / "openstates_bill_introduced.json").read_text("utf-8"))
    bill = parse_bill(raw, session="2026rs")

    assert bill.identifier == raw["identifier"]
    assert bill.title == raw["title"]
    assert bill.openstates_id == raw["id"]
    assert bill.session == "2026rs"
    assert bill.body_ids  # at least the chamber of origin
    assert all(b in {"ky-house", "ky-senate"} for b in bill.body_ids)
    assert bill.actions  # any introduced bill has at least one action
    assert bill.last_action_date  # ISO date string
    assert bill.chamber_progress["lower"] in {"introduced", "in_committee", "passed_committee", "passed"} or \
           bill.chamber_progress["upper"] in {"introduced", "in_committee", "passed_committee", "passed"}


def test_parse_passed_bill_marks_chamber(fixtures_dir):
    raw = json.loads((fixtures_dir / "openstates_bill_passed_house.json").read_text("utf-8"))
    bill = parse_bill(raw, session="2026rs")

    cp = bill.chamber_progress
    assert "passed" in (cp.get("lower"), cp.get("upper"))
    # If lower passed, the chamber-of-origin's body_id is in body_ids
    if cp.get("lower") == "passed":
        assert "ky-house" in bill.body_ids
    if cp.get("upper") == "passed":
        assert "ky-senate" in bill.body_ids


def test_body_ids_includes_other_chamber_after_referral(fixtures_dir):
    """Once a bill is referred to the other chamber, both chambers should appear in body_ids."""
    raw = json.loads((fixtures_dir / "openstates_bill_passed_house.json").read_text("utf-8"))
    bill = parse_bill(raw, session="2026rs")

    has_upper_action = any(
        (a.get("organization") or {}).get("classification") == "upper"
        or a.get("chamber") == "upper"
        for a in raw.get("actions", [])
    )
    if has_upper_action:
        assert "ky-senate" in bill.body_ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_openstates_parsing.py -v`

Expected: ImportError on `scrapers.openstates`.

- [ ] **Step 3: Implement `parse_bill` in `scrapers/openstates.py`**

Create `scrapers/openstates.py`:

```python
"""Open States API v3 adapter.

Pulls Kentucky General Assembly bills (and committee events, if available) into
the existing tracker shape. Bills become a new top-level entity (data/bills/);
events reuse the Meeting model (data/meetings/<lazy-body>/).

Endpoints used (https://docs.openstates.org/api-v3/):
    GET /jurisdictions/{jurisdiction}?include=legislative_sessions
    GET /bills?jurisdiction=...&session=...&include=...
    GET /events?jurisdiction=...&include=...

Auth: header X-API-KEY = $OPENSTATES_API_KEY. Empty/missing key -> caller skips.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
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

# Open States chamber names -> our body slugs
_CHAMBER_TO_BODY = {
    "lower": "ky-house",
    "upper": "ky-senate",
}


def parse_bill(raw: dict[str, Any], session: str) -> Bill:
    """Convert one Open States bill dict into our Bill dataclass."""
    actions = [_parse_action(a) for a in raw.get("actions", []) or []]
    chamber_progress = derive_chamber_progress(actions)

    sponsors = [_parse_sponsor(s) for s in raw.get("sponsorships", []) or []]
    votes = [_parse_vote(v) for v in raw.get("votes", []) or raw.get("vote_events", []) or []]

    abstracts = raw.get("abstracts") or []
    abstract = abstracts[0]["abstract"] if abstracts else None

    subjects = raw.get("subject") or []  # Open States: "subject" is a list of strings

    body_ids = _body_ids_for(raw, actions)
    last_action_date = max((a.date for a in actions), default=raw.get("first_action_date") or "")

    sources = raw.get("sources") or []
    source_url = sources[0]["url"] if sources and "url" in sources[0] else ""

    identifier = raw["identifier"]
    bill_slug = identifier.lower().replace(" ", "")  # "HB 15" -> "hb15"

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
    party = None
    district = None
    # Open States sometimes inlines current_role under person
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
        # Defensive fallback: derive from identifier prefix.
        ident = (raw.get("identifier") or "").upper()
        if ident.startswith(("HB", "HR", "HCR", "HJR")):
            seen.add("ky-house")
        elif ident.startswith(("SB", "SR", "SCR", "SJR")):
            seen.add("ky-senate")
    # Stable order: house first if present, then senate.
    out: list[str] = []
    if "ky-house" in seen:
        out.append("ky-house")
    if "ky-senate" in seen:
        out.append("ky-senate")
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_openstates_parsing.py -v`

Expected: 3 passed. If a test fails because the live fixture key names differ from what the parser expects, edit the parser to match the fixture (the fixture is ground truth — adjust the code, not the data).

- [ ] **Step 5: Commit**

```bash
git add scrapers/openstates.py tests/test_openstates_parsing.py
git commit -m "Parse Open States bill JSON into Bill dataclass"
```

---

### Task 6: Open States scraper class (network calls + pagination + state)

**Files:**
- Modify: `scrapers/openstates.py`

- [ ] **Step 1: Add the scraper class**

Append to `scrapers/openstates.py`:

```python
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
        # `requests` serialises list values as repeated keys, which Open States
        # accepts (e.g. include=actions&include=votes).
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
        # Fallback: most-recent by start_date
        sessions.sort(key=lambda s: s.get("start_date") or "", reverse=True)
        if sessions:
            return sessions[0]["identifier"]
        raise RuntimeError(f"no legislative sessions found for {self.jurisdiction!r}")

    def list_bills(self, session: str) -> Iterator[dict[str, Any]]:
        """Yield raw bill dicts from Open States, paginating until exhausted."""
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

    def list_events(self) -> Iterator[dict[str, Any]]:
        page = 1
        per_page = 20
        while True:
            data = self._get(
                "/events",
                jurisdiction=self.jurisdiction,
                include=["agenda", "related_entities"],
                page=page,
                per_page=per_page,
            )
            for e in data.get("results") or []:
                yield e
            pagination = data.get("pagination") or {}
            if page >= int(pagination.get("max_page") or 1):
                return
            page += 1
```

- [ ] **Step 2: Smoke-test live**

Run:

```bash
OPENSTATES_API_KEY=<key> .venv/Scripts/python.exe -c "
from scrapers.openstates import OpenStatesScraper
s = OpenStatesScraper(__import__('os').environ['OPENSTATES_API_KEY'])
sess = s.current_session()
print(f'session: {sess}')
gen = s.list_bills(sess)
first = next(gen); second = next(gen)
print(f'first bill: {first[\"identifier\"]!r}')
print(f'second bill: {second[\"identifier\"]!r}')
"
```

Expected: prints session slug (e.g. `2026rs`) and two bill identifiers like `HB 1`, `HB 2`.

- [ ] **Step 3: Commit**

```bash
git add scrapers/openstates.py
git commit -m "Add OpenStatesScraper with paginated list_bills + list_events"
```

---

### Task 7: Wire openstates into the orchestrator

**Files:**
- Modify: `scrapers/__main__.py`

- [ ] **Step 1: Add imports + constants**

Edit `scrapers/__main__.py`. Near the existing imports, add:

```python
import os

from scrapers.openstates import (
    OpenStatesScraper,
    parse_bill,
)
```

Below the existing `JCPS_LABEL` constant, add:

```python
KY_BODIES = [
    {"id": "ky-house", "name": "Kentucky House of Representatives"},
    {"id": "ky-senate", "name": "Kentucky Senate"},
]
```

- [ ] **Step 2: Add the openstates run path**

Below `run_ksba`, add:

```python
def run_openstates(args: argparse.Namespace, state: dict, all_bodies: dict) -> tuple[int, int, int]:
    api_key = os.environ.get("OPENSTATES_API_KEY", "").strip()
    if not api_key:
        print("\n[openstates] OPENSTATES_API_KEY not set; skipping.")
        return 0, 0, 0

    selected = {s.strip() for s in (args.bodies or "").split(",") if s.strip()}

    # Register the two static KY bodies up front so the site can render them
    # even before bills land.
    from scrapers.models import Body
    for spec in KY_BODIES:
        b = Body(id=spec["id"], name=spec["name"], source_type="openstates", source_id=spec["id"])
        all_bodies[b.id] = b.to_dict()

    scraper = OpenStatesScraper(api_key)
    print(f"\n[openstates] resolving active session ...")
    session = scraper.current_session()
    print(f"           active session = {session}")

    bills_seen_at = state.setdefault("bills_updated_at", {})

    written = skipped = failed = 0
    bills_dir = DATA_ROOT / "bills" / session
    for raw in scraper.list_bills(session):
        try:
            updated_at = raw.get("updated_at") or ""
            ident = raw.get("identifier") or "?"
            bill_id_for_state = raw["id"]
            if bills_seen_at.get(bill_id_for_state) == updated_at and updated_at:
                skipped += 1
                continue

            bill = parse_bill(raw, session=session)
            if selected and not (set(bill.body_ids) & selected):
                continue

            out = bills_dir / f"{bill.id.split('-', 4)[-1]}.json"
            write_json(out, bill.to_dict())
            bills_seen_at[bill_id_for_state] = updated_at
            written += 1
            if written <= 10 or written % 50 == 0:
                print(f"           [{written}] {ident} -> {out.relative_to(REPO_ROOT)} ({bill.current_status})")
        except Exception as e:  # noqa: BLE001
            print(f"           FAIL bill {raw.get('identifier')}: {e!r}")
            failed += 1

    return written, skipped, failed
```

- [ ] **Step 3: Register openstates source in main()**

Edit `main()` in `scrapers/__main__.py`. After the existing `if "ksba" in sources:` block, add:

```python
    if "openstates" in sources:
        w, s_, f = run_openstates(args, state, all_bodies)
        written += w; skipped += s_; failed += f
```

- [ ] **Step 4: Update the `--sources` default**

Find the `parse_args` function and change the `--sources` default:

```python
    p.add_argument(
        "--sources",
        type=str,
        default="primegov,ksba,openstates",
        help="Comma-separated source names to run (default: primegov,ksba,openstates).",
    )
```

- [ ] **Step 5: Smoke-test**

Run with no key first to confirm graceful skip:

```bash
unset OPENSTATES_API_KEY
.venv/Scripts/python.exe -m scrapers --sources openstates 2>&1 | head -3
```

Expected: prints `OPENSTATES_API_KEY not set; skipping.` and exits cleanly with `Done. written=0 skipped=0 failed=0`.

Then run with a key, scraping just bills:

```bash
OPENSTATES_API_KEY=<key> .venv/Scripts/python.exe -m scrapers --sources openstates 2>&1 | tail -10
```

Expected: writes ≥100 bill JSONs under `data/bills/2026rs/`. State.json gains a `bills_updated_at` map. A second run reports `skipped=N, written=0`.

- [ ] **Step 6: Commit**

```bash
git add scrapers/__main__.py
git commit -m "Wire openstates source into orchestrator with graceful empty-key skip"
```

---

### Task 8: Site data loader — Bill types and accessors

**Files:**
- Modify: `site/src/lib/data.ts`

- [ ] **Step 1: Add Bill types**

Append to `site/src/lib/data.ts` (below the existing `Meeting` interface):

```ts
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
  option: string; // "yes" | "no" | "abstain" | "not voting"
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
```

- [ ] **Step 2: Add the BILLS_DIR constant + loader functions**

Edit `site/src/lib/data.ts`. Just after the existing top-level path constants (`MEETINGS_DIR`, `ATTACHMENTS_DIR`, `BODIES_PATH`), add:

```ts
const BILLS_DIR = path.join(DATA_ROOT, "bills");

let _bills: Bill[] | null = null;
```

At the end of the file (or alongside the existing accessor functions), add:

```ts
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
```

Update the existing `dataPaths` export object to include `BILLS_DIR`:

```ts
export const dataPaths = {
  REPO_ROOT,
  DATA_ROOT,
  MEETINGS_DIR,
  ATTACHMENTS_DIR,
  BODIES_PATH,
  BILLS_DIR,
};
```

- [ ] **Step 3: Verify TypeScript compiles**

Run:

```bash
cd site && npx astro check 2>&1 | tail -20
```

Expected: 0 errors, 0 warnings (or only the existing baseline of warnings if any).

- [ ] **Step 4: Commit**

```bash
git add site/src/lib/data.ts
git commit -m "Add Bill types and accessors to the site data loader"
```

---

### Task 9: Bill detail page

**Files:**
- Create: `site/src/pages/bill/[id].astro`

- [ ] **Step 1: Write the page**

Create `site/src/pages/bill/[id].astro`:

```astro
---
import Layout from "~/layouts/Layout.astro";
import { getBills, getBillById, getBodyById } from "~/lib/data";

export function getStaticPaths() {
  return getBills().map((b) => ({ params: { id: b.id } }));
}

const { id } = Astro.params;
const bill = getBillById(id!);
const base = import.meta.env.BASE_URL;

function chamberLabel(ch: "lower" | "upper" | null): string {
  if (ch === "lower") return "House";
  if (ch === "upper") return "Senate";
  return "";
}

function stateLabel(state: string | null): string {
  if (!state) return "—";
  return state.replace(/_/g, " ");
}
---

<Layout
  title={bill ? `${bill.identifier} — ${bill.title}` : "Bill"}
  description={bill?.title}
>
  {!bill ? (
    <p class="empty-state">No such bill.</p>
  ) : (
    <article data-pagefind-body>
      <p>
        <a href={base}>&larr; Home</a> ·
        <a href={`${base}bills`}>All bills</a>
      </p>
      <h1>{bill.identifier}: {bill.title}</h1>

      <p data-pagefind-meta={`session:${bill.session}`} style="color: var(--fg-muted);">
        <strong>{bill.current_status}</strong> ·
        Session {bill.session} ·
        Last action {bill.last_action_date} ·
        {bill.source_url && (<><a href={bill.source_url} target="_blank" rel="noopener">Source on LRC</a></>)}
      </p>

      <section style="margin: 1rem 0; display: flex; gap: 0.6rem; flex-wrap: wrap;">
        <span class="status-pill">House: {stateLabel(bill.chamber_progress.lower)}</span>
        <span class="status-pill">Senate: {stateLabel(bill.chamber_progress.upper)}</span>
        <span class="status-pill">Gov: {bill.chamber_progress.governor ?? "—"}</span>
        {bill.body_ids.map((bid) => {
          const body = getBodyById(bid);
          return body ? <a class="body-pill" href={`${base}body/${bid}`}>{body.name}</a> : null;
        })}
      </section>

      {bill.abstract && (
        <section>
          <h2>Summary</h2>
          <p>{bill.abstract}</p>
        </section>
      )}

      <section>
        <h2>Sponsors ({bill.sponsors.length})</h2>
        <ul class="items">
          {bill.sponsors.map((s) => (
            <li>
              <span class="num">{s.primary ? "Primary" : "Co"}</span>
              <strong>{s.name}</strong>
              {s.party && <> ({s.party}{s.district ? `-${s.district}` : ""})</>}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2>Actions ({bill.actions.length})</h2>
        <ul class="items">
          {bill.actions.map((a) => (
            <li>
              <span class="num">{a.date}</span>
              {a.chamber && <span class="section-tag">{chamberLabel(a.chamber)}</span>}
              {a.description}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2>Votes ({bill.votes.length})</h2>
        {bill.votes.length === 0 ? (
          <p class="empty-state">No roll-call votes recorded yet.</p>
        ) : (
          bill.votes.map((v, i) => (
            <details class="corpus" open={i === 0}>
              <summary>
                {v.date} · {chamberLabel(v.chamber)} · {v.motion} ·
                <strong>{v.result}</strong>
                ({v.counts.yes}–{v.counts.no})
              </summary>
              <ul class="items">
                {v.member_votes.map((mv) => (
                  <li>
                    <span class="num">{mv.option}</span>
                    {mv.name}
                  </li>
                ))}
              </ul>
            </details>
          ))
        )}
      </section>
    </article>
  )}

  <style>
    .status-pill {
      display: inline-block; font-size: 0.8rem; padding: 3px 10px;
      background: #efeae6; color: #333; border-radius: 12px;
      font-variant-caps: small-caps;
    }
  </style>
</Layout>
```

- [ ] **Step 2: Verify build (will be empty until Task 7 runs to populate `data/bills/`)**

Run:

```bash
cd site && npm run build 2>&1 | tail -5
```

Expected: build succeeds. If `data/bills/` is empty, no `/bill/*` pages are created — that's fine.

- [ ] **Step 3: Commit**

```bash
git add site/src/pages/bill/
git commit -m "Add /bill/[id] detail page with status strip + actions + votes"
```

---

### Task 10: Bills index page

**Files:**
- Create: `site/src/pages/bills.astro`

- [ ] **Step 1: Write the index page**

Create `site/src/pages/bills.astro`:

```astro
---
import Layout from "~/layouts/Layout.astro";
import { getBills } from "~/lib/data";

const bills = getBills();
const base = import.meta.env.BASE_URL;
---

<Layout title="Bills — Kentucky + Louisville Politics" description="Recent Kentucky General Assembly bills.">
  <h1>Bills</h1>
  <p>
    {bills.length} bills tracked in the current Kentucky General Assembly session,
    sorted by most recent action.
  </p>

  <div data-pagefind-ignore>
    {bills.length === 0 && (
      <p class="empty-state">
        No bills yet — set <code>OPENSTATES_API_KEY</code> and run
        <code>python -m scrapers --sources openstates</code> to populate
        <code>data/bills/</code>.
      </p>
    )}
    {bills.map((b) => (
      <a class="meeting-card" href={`${base}bill/${b.id}`}>
        <div class="date">{b.last_action_date}</div>
        <div class="body-name">{b.session} · {b.identifier}</div>
        <div class="title">{b.title}</div>
        <div class="meta">{b.current_status} · {b.sponsors.length} sponsors · {b.votes.length} votes</div>
      </a>
    ))}
  </div>
</Layout>
```

- [ ] **Step 2: Build and curl-verify**

Run:

```bash
cd site && npm run build && (npm run preview &) && sleep 2 && curl -s http://localhost:4321/bills | grep -oE '<h1>[^<]+</h1>|<strong>[0-9]+</strong>' | head; pkill -f 'astro preview' 2>/dev/null || true
```

Expected: `<h1>Bills</h1>` printed, page builds successfully.

- [ ] **Step 3: Commit**

```bash
git add site/src/pages/bills.astro
git commit -m "Add /bills index page sorted by last action date"
```

---

### Task 11: Update body page to surface bills

**Files:**
- Modify: `site/src/pages/body/[id].astro`

- [ ] **Step 1: Edit the body page to render a Bills section**

Edit `site/src/pages/body/[id].astro`. Below the existing `import` line for data accessors, also import `getBillsByBody`:

```ts
import { getBodies, getBodyById, getMeetingsByBody, getBillsByBody, formatMeetingDate } from "~/lib/data";
```

In the script frontmatter, add a bills lookup right after `meetings`:

```ts
const bills = body ? getBillsByBody(body.id) : [];
```

In the body of the template, after the existing meetings loop and `{meetings.length === 0}` block, add a Bills section before the closing `<>`:

```astro
{bills.length > 0 && (
  <section style="margin-top: 2rem;">
    <h2>Bills ({bills.length})</h2>
    <div data-pagefind-ignore>
      {bills.slice(0, 100).map((b) => (
        <a class="meeting-card" href={`${base}bill/${b.id}`}>
          <div class="date">{b.last_action_date}</div>
          <div class="body-name">{b.identifier}</div>
          <div class="title">{b.title}</div>
          <div class="meta">{b.current_status}</div>
        </a>
      ))}
      {bills.length > 100 && (
        <p style="color: var(--fg-muted);">Showing 100 of {bills.length}. Use search for more.</p>
      )}
    </div>
  </section>
)}
```

- [ ] **Step 2: Build and verify**

Run:

```bash
cd site && npm run build 2>&1 | grep -E 'body/ky-(house|senate)|error' | head
```

Expected: lines like `/body/ky-house/index.html` and `/body/ky-senate/index.html`. No errors.

- [ ] **Step 3: Commit**

```bash
git add site/src/pages/body/[id].astro
git commit -m "Show bills under their chamber's body page"
```

---

### Task 12: Home page recent legislative activity

**Files:**
- Modify: `site/src/pages/index.astro`

- [ ] **Step 1: Add bills to the home page**

Edit `site/src/pages/index.astro`. Add `getRecentBills` to the existing data import:

```ts
import { getMeetings, getBodies, formatMeetingDate, getBodyById, getRecentBills } from "~/lib/data";
```

After the existing `const recent = meetings.slice(0, 50);` line, add:

```ts
const recentBills = getRecentBills(10);
```

After the existing main "Recent meetings" block (the `<div data-pagefind-ignore>...</div>` containing meeting cards), and before the `<section>` for "Browse by body", add a new section:

```astro
{recentBills.length > 0 && (
  <section style="margin-top: 2rem;">
    <h2>Recent legislative activity</h2>
    <div data-pagefind-ignore>
      {recentBills.map((b) => (
        <a class="meeting-card" href={`${base}bill/${b.id}`}>
          <div class="date">{b.last_action_date}</div>
          <div class="body-name">{b.identifier} · Session {b.session}</div>
          <div class="title">{b.title}</div>
          <div class="meta">{b.current_status}</div>
        </a>
      ))}
      <p style="margin-top: 0.6rem;"><a href={`${base}bills`}>All bills &rarr;</a></p>
    </div>
  </section>
)}
```

- [ ] **Step 2: Build**

Run: `cd site && npm run build 2>&1 | tail -5`

Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add site/src/pages/index.astro
git commit -m "Add Recent legislative activity to home page"
```

---

### Task 13: Rebrand site to Kentucky + Louisville Politics

**Files:**
- Modify: `site/src/layouts/Layout.astro`

- [ ] **Step 1: Update brand text**

Edit `site/src/layouts/Layout.astro`. Replace the brand link text:

```astro
<a class="brand" href={base}>Kentucky + Louisville Politics</a>
```

Also update the `<meta name="description">` fallback in any pages that use a hard-coded one. (Index page description: replace "Searchable index of Louisville Metro and JCPS Board agendas." with "Searchable index of Kentucky General Assembly bills, Louisville Metro Council, and JCPS Board agendas.")

- [ ] **Step 2: Update home page description**

Edit `site/src/pages/index.astro` Layout call to include the new description:

```astro
<Layout title="Kentucky + Louisville Politics" description="Searchable index of Kentucky General Assembly bills, Louisville Metro Council, and JCPS Board agendas.">
```

- [ ] **Step 3: Build and verify the title shows in HTML**

Run:

```bash
cd site && npm run build && grep -oE '<title>[^<]+</title>' dist/index.html
```

Expected: `<title>Kentucky + Louisville Politics</title>`

- [ ] **Step 4: Commit**

```bash
git add site/src/layouts/Layout.astro site/src/pages/index.astro
git commit -m "Rebrand site to Kentucky + Louisville Politics"
```

---

### Task 14: Pass OPENSTATES_API_KEY through the GH Actions workflow

**Files:**
- Modify: `.github/workflows/scrape-build-deploy.yml`

- [ ] **Step 1: Add the env var to the scrape step**

Edit `.github/workflows/scrape-build-deploy.yml`. In the existing `Scrape` step, add `OPENSTATES_API_KEY` to the `env` block:

```yaml
      - name: Scrape (skip on push events that didn't touch data sources)
        if: github.event_name != 'push'
        env:
          PYTHONUNBUFFERED: "1"
          OPENSTATES_API_KEY: ${{ secrets.OPENSTATES_API_KEY }}
        run: |
          python -m scrapers --year "$(date -u +%Y)" --no-upcoming
          python -m scrapers --year "$(date -u +%Y)" --sources primegov
```

The existing two-line `python -m scrapers ...` body stays as-is. The first invocation now also runs `openstates` (it's in the default `--sources`).

- [ ] **Step 2: Push and verify**

Run:

```bash
git add .github/workflows/scrape-build-deploy.yml
git commit -m "Pass OPENSTATES_API_KEY env var to scrape step"
git push origin main
```

Then in the GH UI (or via `gh secret set`):

```bash
MSYS_NO_PATHCONV=1 gh secret set OPENSTATES_API_KEY --repo uurrnn/kyp0l --body "<key>"
```

- [ ] **Step 3: Trigger the workflow + watch**

Run:

```bash
MSYS_NO_PATHCONV=1 gh workflow run scrape-build-deploy.yml --repo uurrnn/kyp0l --ref main
sleep 5
MSYS_NO_PATHCONV=1 gh run list --repo uurrnn/kyp0l --limit 3
```

Expected: a fresh run shows up in queued/in-progress state. Wait for it to complete (3-10 min depending on bill count).

---

### Task 15: End-to-end verification

- [ ] **Step 1: Verify live site has bills**

Run:

```bash
curl -s https://uurrnn.github.io/kyp0l/bills/ | grep -oE 'bills tracked in the current'
curl -s https://uurrnn.github.io/kyp0l/ | grep -oE 'Recent legislative activity'
```

Expected: both grep matches return non-empty output.

- [ ] **Step 2: Verify bill page renders correctly**

Pick any bill ID from `data/bills/2026rs/` (after `git pull origin main`):

```bash
git pull origin main
ls data/bills/2026rs | head -1
# example: hb15.json -> bill id is openstates-ky-2026rs-hb15
curl -s "https://uurrnn.github.io/kyp0l/bill/openstates-ky-2026rs-hb15" -L | grep -oE '<title>[^<]+</title>|<h1>[^<]+</h1>' | head
```

Expected: title and h1 contain the bill identifier and title.

- [ ] **Step 3: Verify body page integration**

```bash
curl -s "https://uurrnn.github.io/kyp0l/body/ky-house/" -L | grep -oE 'Bills \([0-9]+\)|Meetings'
```

Expected: page shows both "Meetings" and "Bills (N)" sections.

- [ ] **Step 4: Verify Pagefind indexes bills**

In a browser, hit `https://uurrnn.github.io/kyp0l/search` and search for a known bill subject (e.g. "education"). Expected: bill results appear alongside meeting results.

- [ ] **Step 5: Update memory**

Add status update to `C:\Users\uurrn\.claude\projects\C--Users-uurrn-projects-proj\memory\project_louisville_tracker.md` reflecting Phase 3 deployment.

- [ ] **Step 6: Commit any final tweaks**

```bash
git add docs/superpowers/plans/
git commit -m "Phase 3 complete: KY state legislature live"
git push origin main
```

---

## Self-review notes

- Every spec requirement maps to a task: data model (Tasks 2–4), scraper (Tasks 1, 5–7), site (Tasks 8–13), workflow (Task 14), verification (Task 15).
- No placeholders remain. Every code-change step has full code; every command step has the command and expected output.
- Type names are consistent across tasks (`Bill`, `Sponsor`, `Action`, `Vote`, `MemberVote`, `chamber_progress`, `current_status`, `body_ids`).
- Test fixtures (Task 1) are captured before any test code runs (Task 2 onwards), so tests assert against ground truth, not speculation.
- Empty-key path is exercised at Task 7 step 5 to confirm the workflow stays green even without the secret.
- Events scraper (originally Task 7 in the spec) is intentionally deferred: if Task 1's probe shows event data is sparse for KY, this plan ships bills-only and a follow-up plan picks up events. The data model already supports events via the existing `Meeting` shape, so no schema work is wasted.
