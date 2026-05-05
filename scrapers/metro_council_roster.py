"""Loader for the hand-curated Louisville Metro Council roster.

This is *not* a scraper — there's no upstream public API for council members.
We materialise the seed file at `data/people/_seed_metro_council.json` into one
`Person` record per member.

The seed format is:
    {"members": [{"district": int, "name": str, "party": str, ...}, ...]}

Optional per-row fields: photo_url, email, website.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator

from scrapers.models import Person, slugify


SEED_RELATIVE = Path("data") / "people" / "_seed_metro_council.json"
BODY_ID = "metro-council"
SOURCE = "metro-council"


def _slug(name: str) -> str:
    return f"metro-council-{slugify(name)}"


def load_seed(repo_root: Path) -> Iterator[Person]:
    """Yield one Person per member in the seed file."""
    seed_path = repo_root / SEED_RELATIVE
    if not seed_path.exists():
        raise FileNotFoundError(seed_path)

    raw = json.loads(seed_path.read_text(encoding="utf-8"))
    members = raw.get("members") or []

    for m in members:
        name = (m.get("name") or "").strip()
        if not name:
            continue

        district = m.get("district")
        slug = _slug(name)

        contact: dict = {"addresses": [], "phones": [], "emails": [], "links": []}
        if m.get("email"):
            contact["emails"].append(m["email"])
        if m.get("website"):
            contact["links"].append(m["website"])

        sources: list[str] = []
        if m.get("source_url"):
            sources.append(m["source_url"])

        yield Person(
            id=slug,
            source=SOURCE,
            source_id=slug,  # self-id; no upstream key
            name=name,
            body_id=BODY_ID,
            chamber=None,
            party=m.get("party"),
            district=str(district) if district is not None else None,
            active=True,
            photo_url=m.get("photo_url"),
            contact=contact,
            sources=sources,
        )
