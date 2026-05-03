"""Find a PrimeGov endpoint that returns agenda *items* (not just meetings).

Strategy:
1. Hit /api/meeting/search and dump one full meeting JSON to see what fields
   civic-scraper is throwing away. Maybe items are right there.
2. If not, try the documented v2/PublicPortal endpoints and a few obvious paths
   like /api/meeting/{id}, /api/agenda/{id}, /Portal/MeetingPreview?... (HTML).
3. Settle on whichever returns the agenda items and is easiest to parse.

Run: python scratch/probe_items.py
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import requests

BASE = "https://louisvilleky.primegov.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; louisville-politics-tracker probe)",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
}


def get(path: str, **params) -> tuple[int, str, str]:
    r = requests.get(f"{BASE}{path}", params=params, headers=HEADERS, timeout=20)
    return r.status_code, r.headers.get("content-type", ""), r.text


def main() -> None:
    end = date.today()
    start = end - timedelta(days=30)
    s, e = start.strftime("%m/%d/%Y"), end.strftime("%m/%d/%Y")

    print("=== /api/meeting/search (raw shape) ===")
    code, ct, body = get("/api/meeting/search", **{"from": s, "to": e})
    print(f"  status={code}  content-type={ct}  bytes={len(body)}")
    try:
        data = json.loads(body)
        print(f"  list length: {len(data)}")
        if data:
            first = data[0]
            print(f"  first meeting top-level keys: {sorted(first.keys())}")
            # dump the first meeting (truncated)
            dump = json.dumps(first, indent=2, default=str)
            print(dump[:2500])
            # remember an id to use below
            sample_id = first.get("id") or first.get("meetingId")
            sample_doc = None
            for t in first.get("templates", []) or []:
                for d in t.get("compiledMeetingDocumentFiles", []) or []:
                    sample_doc = d.get("id")
                    break
                if sample_doc:
                    break
            print(f"\n  sample meeting id = {sample_id}")
            print(f"  sample compiled doc id = {sample_doc}")
        else:
            sample_id, sample_doc = None, None
    except json.JSONDecodeError:
        print("  not JSON; head:")
        print(body[:500])
        return

    if not sample_id:
        print("no sample id; bail")
        return

    candidates: list[tuple[str, dict]] = [
        # known from civic-scraper docstring
        (f"/v2/PublicPortal/ListUpcomingMeetings", {}),
        (f"/v2/PublicPortal/ListArchivedMeetings", {"year": end.year}),
        # speculative item endpoints
        (f"/api/meeting/{sample_id}", {}),
        (f"/api/meeting/{sample_id}/items", {}),
        (f"/api/agenda/{sample_id}", {}),
        (f"/api/meeting/agendaitems", {"meetingId": sample_id}),
        (f"/api/agendaitem/search", {"meetingId": sample_id}),
        (f"/Portal/Meeting", {"meetingTemplateId": sample_id}),
    ]
    if sample_doc:
        candidates += [
            (f"/Portal/MeetingPreview", {"compiledMeetingDocumentFileId": sample_doc}),
            (f"/api/document/{sample_doc}", {}),
            (f"/api/agenda/document/{sample_doc}", {}),
        ]

    for path, params in candidates:
        try:
            code, ct, body = get(path, **params)
        except Exception as ex:  # noqa: BLE001
            print(f"\n--- {path} {params} -> EXC {ex!r}")
            continue
        head = body[:200].replace("\n", " ")
        print(f"\n--- {path} {params}")
        print(f"  status={code}  ct={ct}  bytes={len(body)}  head: {head}")


if __name__ == "__main__":
    main()
