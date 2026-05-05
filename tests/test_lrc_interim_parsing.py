"""Parser tests for the LRC interim joint committee scraper."""

import json

from scrapers.lrc_interim import (
    LrcCommittee,
    parse_committee_detail,
    parse_documents_page,
    parse_landing,
    parse_lrc_date,
    write_committee_index,
)


def test_parse_landing_extracts_committees(fixtures_dir):
    html = (fixtures_dir / "lrc_interim_landing.html").read_text(encoding="utf-8")
    committees = parse_landing(html)
    assert len(committees) >= 15  # ~20 committees on the live page

    # Spot-check Education
    edu = next(c for c in committees if c.name == "Education")
    assert edu.rsn == "29"
    assert edu.body_id == "lrc-interim-education"
    assert "Committee-Details.aspx?CommitteeRSN=29" in edu.detail_url
    assert edu.detail_url.startswith("https://legislature.ky.gov")

    # All slugs unique
    slugs = [c.body_id for c in committees]
    assert len(slugs) == len(set(slugs))


def test_parse_committee_detail_education(fixtures_dir):
    html = (fixtures_dir / "lrc_committee_detail_education.html").read_text(encoding="utf-8")
    c = LrcCommittee(rsn="29", name="Education", detail_url="x", body_id="lrc-interim-education")
    parse_committee_detail(html, c)

    assert c.documents_id == "28"
    # Education has lots of members
    assert len(c.member_districts) >= 30
    assert all(d.isdigit() for d in c.member_districts)
    # Jurisdiction text starts with "Matters pertaining to public elementary..."
    assert "elementary" in c.jurisdiction.lower()


def test_parse_documents_page_extracts_meetings(fixtures_dir):
    html = (fixtures_dir / "lrc_documents_education.html").read_text(encoding="utf-8")
    rows = parse_documents_page(html, base_url="https://apps.legislature.ky.gov/CommitteeDocuments/28/")

    # Education's docs page has multiple 2025 meetings (Jun-Dec at least)
    assert len(rows) >= 4
    # All rows have parsed dates and a folder id
    for r in rows:
        assert r.date_iso and len(r.date_iso) == 10
        assert r.folder_id and r.folder_id.isdigit()
        assert r.attachments and all(url.startswith("http") for _, url in r.attachments)

    # First row is most recent (Dec 9 in the captured fixture)
    first = rows[0]
    assert first.date_iso.startswith("2025-12") or first.date_iso.startswith("2025-")
    assert any("agenda" in fname.lower() for fname, _ in first.attachments)


def test_parse_lrc_date_handles_full_dayname():
    assert parse_lrc_date("Tuesday, December 9, 2025") == "2025-12-09"
    assert parse_lrc_date("Monday, July 14, 2025") == "2025-07-14"


def test_parse_lrc_date_handles_no_dayname():
    assert parse_lrc_date("December 9, 2025") == "2025-12-09"


def test_parse_lrc_date_returns_empty_on_garbage():
    assert parse_lrc_date("") == ""
    assert parse_lrc_date("Other Meeting Years") == ""
    assert parse_lrc_date("not a date") == ""


def test_write_committee_index_round_trips_member_districts(fixtures_dir, tmp_path):
    detail = (fixtures_dir / "lrc_committee_detail_education.html").read_text(encoding="utf-8")
    edu = LrcCommittee(rsn="29", name="Education", detail_url="x", body_id="lrc-interim-education")
    parse_committee_detail(detail, edu)
    # Sanity-check enrich produced a documents id and members.
    assert edu.documents_id == "28"
    assert len(edu.member_districts) >= 30

    out = write_committee_index([edu], tmp_path)
    assert out.exists()
    payload = json.loads(out.read_text("utf-8"))
    assert "lrc-interim-education" in payload
    rec = payload["lrc-interim-education"]
    assert rec["name"] == "Interim Joint Committee on Education"
    assert rec["documents_id"] == "28"
    assert isinstance(rec["member_districts"], list)
    assert all(isinstance(d, str) for d in rec["member_districts"])
    assert len(rec["member_districts"]) == len(edu.member_districts)
