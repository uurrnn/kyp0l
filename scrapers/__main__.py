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
import sys
from datetime import date
from pathlib import Path
from typing import Iterable

from scrapers.ksba import KsbaScraper, write_meeting_record as write_ksba_meeting
from scrapers.models import Body, write_json, read_json
from scrapers.primegov import (
    PrimeGovScraper,
    list_all_meetings,
    write_meeting_record,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data"
ATTACHMENTS_DIR = DATA_ROOT / "attachments"
STATE_PATH = DATA_ROOT / "state.json"
BODIES_PATH = DATA_ROOT / "bodies.json"

LOUISVILLE_INSTANCE = "louisvilleky"
JCPS_KSBA_AGENCY_ID = 89
JCPS_LABEL = "JCPS Board of Education"


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
        default="primegov,ksba",
        help="Comma-separated source names to run (default: primegov,ksba).",
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
