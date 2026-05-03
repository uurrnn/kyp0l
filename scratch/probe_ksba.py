"""Probe KSBA Public Portal for JCPS (PublicAgencyID=89).

Original plan said JCPS uses BoardDocs. That was wrong — JCPS uses KSBA's
portal at portal.ksba.org/public/Agency.aspx?PublicAgencyID=89. This probe
validates the agency page → meeting page → attachment chain works without
auth or JS execution.

Run: python scratch/probe_ksba.py
"""

from __future__ import annotations

import sys

import requests
from bs4 import BeautifulSoup

BASE = "https://portal.ksba.org/public"
JCPS_AGENCY_ID = 89
HEADERS = {"User-Agent": "louisville-politics-tracker probe"}


def main() -> int:
    s = requests.Session()
    s.headers.update(HEADERS)

    # 1) Agency page lists meetings.
    r = s.get(f"{BASE}/Agency.aspx", params={"PublicAgencyID": JCPS_AGENCY_ID})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    board_table = soup.find("table", id="Board-meetings-table")
    if board_table is None:
        print("FAIL: no Board-meetings-table on agency page")
        return 2
    rows = board_table.find_all("tr")
    print(f"OK: agency page has Board-meetings-table with {len(rows)} rows")

    # 2) First meeting link
    first_meeting_link = board_table.find("a", href=lambda h: h and "Meeting.aspx" in h)
    if first_meeting_link is None:
        print("FAIL: no meeting link in board table")
        return 3
    href = first_meeting_link["href"]
    print(f"OK: first meeting href = {href}")

    # 3) Fetch one meeting page
    r2 = s.get(f"{BASE}/{href}")
    r2.raise_for_status()
    msoup = BeautifulSoup(r2.text, "lxml")
    headers = msoup.find_all(class_="AgendaItemHeader")
    attaches = msoup.find_all("a", href=lambda h: h and "DisplayAttachment" in h)
    print(f"OK: meeting page has {len(headers)} AgendaItemHeader blocks, {len(attaches)} attachments")

    # 4) Validate one attachment download (HEAD only, no need to pull bytes)
    if attaches:
        att_href = attaches[0]["href"]
        r3 = s.head(f"{BASE}/{att_href}", allow_redirects=True)
        ct = r3.headers.get("content-type", "")
        print(f"OK: HEAD {att_href[:80]}... -> {r3.status_code} {ct}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
