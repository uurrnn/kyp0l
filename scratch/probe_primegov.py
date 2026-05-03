"""Throwaway probe: confirm civic-scraper can talk to louisvilleky.primegov.com.

This is the riskiest assumption in the plan. If this works end-to-end, we
can build the rest of Phase 1 with confidence. If it fails, we course-correct
before scaffolding more.

Run: python scratch/probe_primegov.py
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta


def main() -> int:
    try:
        # civic-scraper 1.x: PrimeGovSite lives at platforms.primegov.site
        from civic_scraper.platforms.primegov.site import PrimeGovSite
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: import PrimeGovSite -> {e!r}")
        print("Run: pip install civic-scraper")
        return 2

    # PrimeGov instance URL pattern is <subdomain>.primegov.com.
    # Louisville's portal lives at louisvilleky.primegov.com.
    # Trailing "/" matters: civic-scraper's _get_meeting_id regex requires it.
    base_url = "https://louisvilleky.primegov.com/"

    # civic-scraper's PrimeGov adapter passes dates straight into the API URL,
    # which expects m/d/Y (e.g. 4/2/2026), not ISO.
    end = date.today()
    start = end - timedelta(days=30)
    start_str = start.strftime("%m/%d/%Y")
    end_str = end.strftime("%m/%d/%Y")

    try:
        site = PrimeGovSite(base_url)
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: PrimeGovSite({base_url!r}) -> {e!r}")
        return 3

    print(f"OK: instantiated PrimeGovSite({base_url!r})")
    print(f"    fetching meetings {start_str} .. {end_str} ...")

    try:
        # civic-scraper's standard interface is .scrape(start_date=, end_date=).
        # Returns an AssetCollection of Asset objects (agendas, minutes, video).
        assets = site.scrape(start_date=start_str, end_date=end_str)
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: site.scrape(...) -> {e!r}")
        return 4

    items = list(assets)
    print(f"OK: scrape returned {len(items)} asset(s)")

    if not items:
        print("WARN: zero assets returned. Either nothing happened in the window,")
        print("      or the subdomain/scrape API is wrong. Investigate before continuing.")
        return 1

    # Show the first 3 so we can eyeball the shape.
    for i, a in enumerate(items[:3]):
        print(f"\n--- asset {i} ---")
        # Asset is a dataclass-ish object; dump whatever attrs it has.
        attrs = {k: v for k, v in vars(a).items() if not k.startswith("_")}
        print(json.dumps(attrs, default=str, indent=2)[:2000])

    return 0


if __name__ == "__main__":
    sys.exit(main())
