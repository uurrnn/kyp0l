"""Orchestrator for the Louisville politics tracker scrapers.

Phase 1 implementation: PrimeGov only. JCPS BoardDocs is wired up as a stub
and will return 0 meetings until probed and implemented.

Usage:
    python -m scrapers --year 2026 --bodies metro-council,abc-board
    python -m scrapers --year 2026 --limit 5
    python -m scrapers --since 2026-04-01

State (data/state.json) keeps track of which meetings we've already written
and the sha256 of their primary attachment, so re-runs are cheap.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path
from typing import Iterable

from scrapers.ksba import KsbaScraper, write_meeting_record as write_ksba_meeting
from scrapers.lrc_interim import (
    LrcInterimScraper,
    committee_body as lrc_committee_body,
    write_meeting_record as write_lrc_meeting,
)
from scrapers.metro_council_roster import load_seed as load_metro_council_seed
from scrapers.models import Body, Person, write_json, read_json
from scrapers.openstates import OpenStatesScraper, parse_bill, parse_person
from scrapers.primegov import (
    PrimeGovScraper,
    list_all_meetings,
    write_meeting_record,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data"
ATTACHMENTS_DIR = DATA_ROOT / "attachments"
PEOPLE_DIR = DATA_ROOT / "people"
PEOPLE_INDEX_PATH = PEOPLE_DIR / "_index.json"
STATE_PATH = DATA_ROOT / "state.json"
BODIES_PATH = DATA_ROOT / "bodies.json"

LOUISVILLE_INSTANCE = "louisvilleky"
JCPS_KSBA_AGENCY_ID = 89
JCPS_LABEL = "JCPS Board of Education"

KY_BODIES = [
    {"id": "ky-house", "name": "Kentucky House of Representatives"},
    {"id": "ky-senate", "name": "Kentucky Senate"},
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="scrapers")
    p.add_argument(
        "--year",
        type=int,
        default=date.today().year,
        help="Calendar year of meetings to fetch (default: current year).",
    )
    p.add_argument(
        "--bodies",
        type=str,
        default="",
        help="Comma-separated body slugs to include (default: all).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Stop after N meetings (debugging).",
    )
    p.add_argument(
        "--since",
        type=str,
        default="",
        help="ISO date YYYY-MM-DD; skip meetings on or before this date.",
    )
    p.add_argument(
        "--instance",
        type=str,
        default=LOUISVILLE_INSTANCE,
        help="PrimeGov instance subdomain (default: louisvilleky).",
    )
    p.add_argument(
        "--no-upcoming",
        action="store_true",
        help="Skip the ListUpcomingMeetings call.",
    )
    p.add_argument(
        "--sources",
        type=str,
        default="primegov,ksba,openstates,people,lrc-interim",
        help=(
            "Comma-separated source names to run "
            "(default: primegov,ksba,openstates,people,lrc-interim)."
        ),
    )
    return p.parse_args(argv)


def filter_bodies(bodies: list[Body], slugs: Iterable[str]) -> list[Body]:
    wanted = {s.strip() for s in slugs if s.strip()}
    if not wanted:
        return bodies
    return [b for b in bodies if b.id in wanted]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)

    sources = {s.strip() for s in args.sources.split(",") if s.strip()}
    state: dict = read_json(STATE_PATH, default={"meetings": {}})
    all_bodies: dict[str, dict] = read_json(BODIES_PATH, default={}) or {}

    written = skipped = failed = 0

    if "primegov" in sources:
        w, s_, f = run_primegov(args, state, all_bodies)
        written += w; skipped += s_; failed += f

    if "ksba" in sources:
        w, s_, f = run_ksba(args, state, all_bodies)
        written += w; skipped += s_; failed += f

    if "openstates" in sources:
        w, s_, f = run_openstates(args, state, all_bodies)
        written += w; skipped += s_; failed += f

    if "people" in sources:
        w, s_, f = run_people(args, all_bodies)
        written += w; skipped += s_; failed += f

    if "lrc-interim" in sources:
        w, s_, f = run_lrc_interim(args, state, all_bodies)
        written += w; skipped += s_; failed += f

    write_json(BODIES_PATH, all_bodies)
    write_json(STATE_PATH, state)
    print(f"\nDone. written={written} skipped={skipped} failed={failed}")
    return 0


def run_primegov(args: argparse.Namespace, state: dict, all_bodies: dict) -> tuple[int, int, int]:
    scraper = PrimeGovScraper(args.instance)
    print(f"\n[primegov] Fetching body list from {args.instance}.primegov.com ...")
    bodies = scraper.list_bodies()
    print(f"           got {len(bodies)} bodies")

    selected_bodies = filter_bodies(bodies, args.bodies.split(","))
    body_by_source_id = {b.source_id: b for b in selected_bodies}
    for b in bodies:
        all_bodies[b.id] = b.to_dict()

    print(f"[primegov] Listing meetings for year {args.year} ...")
    raw_meetings = list_all_meetings(
        scraper, [args.year], include_upcoming=not args.no_upcoming
    )
    print(f"           got {len(raw_meetings)} raw meeting records")

    if args.bodies:
        raw_meetings = [m for m in raw_meetings if str(m.get("committeeId")) in body_by_source_id]
        print(f"           filtered to {len(raw_meetings)} after --bodies")
    if args.since:
        raw_meetings = [m for m in raw_meetings if (m.get("dateTime") or "") > args.since]
        print(f"           filtered to {len(raw_meetings)} after --since {args.since}")
    if args.limit:
        raw_meetings = raw_meetings[: args.limit]
        print(f"           capped to {len(raw_meetings)} via --limit")

    written = skipped = failed = 0
    for i, raw in enumerate(raw_meetings, 1):
        cid = str(raw.get("committeeId") or "")
        body = body_by_source_id.get(cid) or _find_or_make_body(bodies, raw)
        if body is None:
            failed += 1
            continue
        try:
            meeting = scraper.fetch_meeting(raw, body, ATTACHMENTS_DIR)
        except Exception as e:  # noqa: BLE001
            print(f"           [{i}/{len(raw_meetings)}] FAIL  id={raw.get('id')}: {e!r}")
            failed += 1
            continue

        prev = state["meetings"].get(meeting.id, {})
        primary_sha = meeting.attachments[0].sha256 if meeting.attachments else None
        if prev.get("primary_sha") == primary_sha and prev.get("items_count") == len(meeting.items):
            skipped += 1
        else:
            path = write_meeting_record(meeting, DATA_ROOT)
            state["meetings"][meeting.id] = {
                "primary_sha": primary_sha,
                "items_count": len(meeting.items),
                "path": str(path.relative_to(REPO_ROOT).as_posix()),
            }
            written += 1
            print(
                f"           [{i}/{len(raw_meetings)}] {meeting.body_id} {meeting.date} "
                f"{meeting.title[:40]:40s} items={len(meeting.items)} attachments={len(meeting.attachments)}"
            )
    return written, skipped, failed


def run_ksba(args: argparse.Namespace, state: dict, all_bodies: dict) -> tuple[int, int, int]:
    scraper = KsbaScraper(JCPS_KSBA_AGENCY_ID, JCPS_LABEL)
    body = scraper.body()
    all_bodies[body.id] = body.to_dict()

    selected = args.bodies.split(",") if args.bodies else []
    if selected and body.id not in {s.strip() for s in selected}:
        return 0, 0, 0

    print(f"\n[ksba] Listing JCPS Board meetings (page 1, ~25 most recent) ...")
    rows = scraper.list_meeting_rows()
    print(f"       got {len(rows)} meeting rows")

    if args.since:
        rows = [r for r in rows if r.date > args.since]
        print(f"       filtered to {len(rows)} after --since {args.since}")
    if args.limit:
        rows = rows[: args.limit]
        print(f"       capped to {len(rows)} via --limit")

    written = skipped = failed = 0
    for i, row in enumerate(rows, 1):
        try:
            meeting = scraper.fetch_meeting(row, body, ATTACHMENTS_DIR)
        except Exception as e:  # noqa: BLE001
            print(f"       [{i}/{len(rows)}] FAIL pmid={row.public_meeting_id}: {e!r}")
            failed += 1
            continue

        prev = state["meetings"].get(meeting.id, {})
        primary_sha = meeting.attachments[0].sha256 if meeting.attachments else None
        if prev.get("primary_sha") == primary_sha and prev.get("items_count") == len(meeting.items):
            skipped += 1
        else:
            path = write_ksba_meeting(meeting, DATA_ROOT)
            state["meetings"][meeting.id] = {
                "primary_sha": primary_sha,
                "items_count": len(meeting.items),
                "path": str(path.relative_to(REPO_ROOT).as_posix()),
            }
            written += 1
            print(
                f"       [{i}/{len(rows)}] {meeting.body_id} {meeting.date} "
                f"{meeting.title[:50]:50s} items={len(meeting.items)} attachments={len(meeting.attachments)}"
            )
    return written, skipped, failed


def run_lrc_interim(args: argparse.Namespace, state: dict, all_bodies: dict) -> tuple[int, int, int]:
    """Discover KY LRC interim joint committees and scrape their meetings."""
    scraper = LrcInterimScraper()
    print("\n[lrc-interim] discovering interim joint committees ...")
    try:
        committees = scraper.list_committees()
    except Exception as e:  # noqa: BLE001
        print(f"             FAIL listing committees: {e!r}")
        return 0, 0, 1
    print(f"             found {len(committees)} committees")

    selected = {s.strip() for s in (args.bodies or "").split(",") if s.strip()}
    if selected:
        committees = [c for c in committees if c.body_id in selected]
        print(f"             filtered to {len(committees)} after --bodies")

    written = skipped = failed = 0
    for ci, c in enumerate(committees, 1):
        print(f"             [{ci}/{len(committees)}] {c.name}")
        try:
            scraper.enrich_committee(c)
        except Exception as e:  # noqa: BLE001
            print(f"               enrich FAIL ({e!r}); skipping")
            failed += 1
            continue
        if not c.documents_id:
            print("               no CommitteeDocuments link; skipping")
            skipped += 1
            continue
        all_bodies[c.body_id] = lrc_committee_body(c).to_dict()

        try:
            rows = scraper.list_meetings(c)
        except Exception as e:  # noqa: BLE001
            print(f"               list_meetings FAIL ({e!r})")
            failed += 1
            continue

        # No --year filter for LRC: the documents page already scopes to the
        # current interim period (older years are on separate ./<year>.html
        # pages we don't fetch in v1).
        if args.since:
            rows = [r for r in rows if r.date_iso > args.since]
        if args.limit:
            rows = rows[: args.limit]
        print(f"               {len(rows)} meetings to consider")

        for ri, row in enumerate(rows, 1):
            try:
                meeting = scraper.fetch_meeting(row, c, ATTACHMENTS_DIR)
            except Exception as e:  # noqa: BLE001
                print(f"                 [{ri}/{len(rows)}] FAIL folder={row.folder_id}: {e!r}")
                failed += 1
                continue

            prev = state["meetings"].get(meeting.id, {})
            # Pick the agenda sha (first attachment with a populated sha) so the
            # incremental check is meaningful — not all attachments are downloaded.
            primary_sha = next(
                (a.sha256 for a in meeting.attachments if a.sha256),
                None,
            )
            if prev.get("primary_sha") == primary_sha and prev.get("items_count") == len(meeting.items):
                skipped += 1
            else:
                path = write_lrc_meeting(meeting, DATA_ROOT)
                state["meetings"][meeting.id] = {
                    "primary_sha": primary_sha,
                    "items_count": len(meeting.items),
                    "path": str(path.relative_to(REPO_ROOT).as_posix()),
                }
                written += 1
                print(
                    f"                 [{ri}/{len(rows)}] {meeting.date} "
                    f"items={len(meeting.items)} attachments={len(meeting.attachments)}"
                )
    return written, skipped, failed


def run_openstates(args: argparse.Namespace, state: dict, all_bodies: dict) -> tuple[int, int, int]:
    api_key = os.environ.get("OPENSTATES_API_KEY", "").strip()
    if not api_key:
        print("\n[openstates] OPENSTATES_API_KEY not set; skipping.")
        return 0, 0, 0

    selected = {s.strip() for s in (args.bodies or "").split(",") if s.strip()}

    for spec in KY_BODIES:
        b = Body(id=spec["id"], name=spec["name"], source_type="openstates", source_id=spec["id"])
        all_bodies[b.id] = b.to_dict()

    scraper = OpenStatesScraper(api_key)
    print("\n[openstates] resolving active session ...")
    session = scraper.current_session()
    print(f"             active session = {session}")

    bills_seen_at = state.setdefault("bills_updated_at", {})

    written = skipped = failed = 0
    bills_dir = DATA_ROOT / "bills" / session

    for raw in scraper.list_bills(session):
        try:
            updated_at = raw.get("updated_at") or ""
            ident = raw.get("identifier") or "?"
            os_id = raw["id"]
            if updated_at and bills_seen_at.get(os_id) == updated_at:
                skipped += 1
                continue

            bill = parse_bill(raw, session=session)
            if selected and not (set(bill.body_ids) & selected):
                skipped += 1
                continue

            # bill.id encodes the slug as its last segment ("...-2026rs-hb15")
            bill_slug = bill.id.rsplit("-", 1)[-1]
            out = bills_dir / f"{bill_slug}.json"
            write_json(out, bill.to_dict())
            bills_seen_at[os_id] = updated_at
            written += 1
            if written <= 10 or written % 50 == 0:
                print(f"             [{written}] {ident:8s} -> {out.relative_to(REPO_ROOT)}  ({bill.current_status})")
                # Periodic state flush so a crash doesn't lose the dedup map.
                write_json(STATE_PATH, state)
            if args.limit and written >= args.limit:
                print(f"             stopped at --limit {args.limit}")
                break
        except Exception as e:  # noqa: BLE001
            print(f"             FAIL bill {raw.get('identifier')}: {e!r}")
            failed += 1

    return written, skipped, failed


def run_people(args: argparse.Namespace, all_bodies: dict) -> tuple[int, int, int]:
    """Build the people roster.

    - KY legislators come from Open States `/people` (needs OPENSTATES_API_KEY).
    - Metro Council members come from a hand-curated seed file.

    Both write `data/people/<slug>.json` and refresh `data/people/_index.json`,
    a `source_id -> our_slug` map used at site-build time to translate the
    upstream `person_id` on bill sponsors/voters into our profile URLs.
    """
    PEOPLE_DIR.mkdir(parents=True, exist_ok=True)
    people_index: dict[str, str] = {}
    written = skipped = failed = 0

    # --- Open States KY legislators -----------------------------------------
    api_key = os.environ.get("OPENSTATES_API_KEY", "").strip()
    if api_key:
        scraper = OpenStatesScraper(api_key)
        print("\n[people] fetching KY legislators from Open States ...")
        seen_slugs: dict[str, str] = {}  # slug -> source_id for collision check
        count = 0
        try:
            for raw in scraper.list_people():
                count += 1
                try:
                    person = parse_person(raw)
                except Exception as e:  # noqa: BLE001
                    print(f"          parse FAIL {raw.get('id')}: {e!r}")
                    failed += 1
                    continue
                if person is None:
                    skipped += 1
                    continue
                # Collision-safe slug: append numeric suffix if two people resolve
                # to the same slug.
                base_slug = person.id
                slug = base_slug
                n = 2
                while slug in seen_slugs and seen_slugs[slug] != person.source_id:
                    slug = f"{base_slug}-{n}"
                    n += 1
                if slug != person.id:
                    person = dc_replace_id(person, slug)
                seen_slugs[slug] = person.source_id

                people_index[person.source_id] = person.id
                write_json(PEOPLE_DIR / f"{person.id}.json", person.to_dict())
                written += 1
                if args.limit and written >= args.limit:
                    print(f"          stopped at --limit {args.limit}")
                    break
        except Exception as e:  # noqa: BLE001
            print(f"          [people] Open States listing failed: {e!r}")
            failed += 1
        print(f"          got {count} raw people, wrote {written} new/updated")
    else:
        print("\n[people] OPENSTATES_API_KEY not set; skipping KY legislators.")

    # --- Metro Council from hand-curated seed -------------------------------
    print("\n[people] loading Metro Council from seed ...")
    try:
        # Ensure body record exists so /body/metro-council resolves even before
        # PrimeGov has run.
        if "metro-council" not in all_bodies:
            all_bodies["metro-council"] = Body(
                id="metro-council",
                name="Metro Council",
                source_type="primegov",
                source_id="1",
            ).to_dict()

        for person in load_metro_council_seed(REPO_ROOT):
            people_index[person.source_id] = person.id
            write_json(PEOPLE_DIR / f"{person.id}.json", person.to_dict())
            written += 1
        print(f"          wrote Metro Council seed roster")
    except FileNotFoundError as e:
        print(f"          seed missing: {e}")
        skipped += 1
    except Exception as e:  # noqa: BLE001
        print(f"          [people] Metro Council seed failed: {e!r}")
        failed += 1

    # --- Merge with any prior index so partial runs don't blow it away ------
    prior = read_json(PEOPLE_INDEX_PATH, default={}) or {}
    prior.update(people_index)
    write_json(PEOPLE_INDEX_PATH, prior)
    print(f"[people] index now has {len(prior)} entries -> {PEOPLE_INDEX_PATH.relative_to(REPO_ROOT)}")
    return written, skipped, failed


def dc_replace_id(person: Person, new_id: str) -> Person:
    """Return a copy of `person` with `id=new_id`."""
    import dataclasses as _dc
    return _dc.replace(person, id=new_id)


def _find_or_make_body(bodies: list[Body], raw_meeting: dict) -> Body | None:
    """Some meetings reference committeeIds that aren't in the public-portal list.
    Fall back to constructing a body from the meeting title when needed.
    """
    cid = str(raw_meeting.get("committeeId") or "")
    for b in bodies:
        if b.source_id == cid:
            return b
    title = (raw_meeting.get("title") or "").strip()
    if not title or not cid:
        return None
    from scrapers.models import slugify
    return Body(id=slugify(title), name=title, source_type="primegov", source_id=cid)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
