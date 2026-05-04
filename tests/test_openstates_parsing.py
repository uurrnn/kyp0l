import json

from scrapers.openstates import parse_bill


def test_parse_introduced_bill(fixtures_dir):
    raw = json.loads((fixtures_dir / "openstates_bill_introduced.json").read_text("utf-8"))
    bill = parse_bill(raw, session="2026rs")

    assert bill.identifier == raw["identifier"]
    assert bill.title == raw["title"]
    assert bill.openstates_id == raw["id"]
    assert bill.session == "2026rs"
    assert bill.body_ids
    assert all(b in {"ky-house", "ky-senate"} for b in bill.body_ids)
    assert bill.actions
    assert bill.last_action_date


def test_parse_passed_bill_marks_chamber(fixtures_dir):
    raw = json.loads((fixtures_dir / "openstates_bill_passed_house.json").read_text("utf-8"))
    bill = parse_bill(raw, session="2026rs")

    cp = bill.chamber_progress
    assert "passed" in (cp.get("lower"), cp.get("upper"))
    if cp.get("lower") == "passed":
        assert "ky-house" in bill.body_ids
    if cp.get("upper") == "passed":
        assert "ky-senate" in bill.body_ids


def test_body_ids_includes_other_chamber_after_referral(fixtures_dir):
    raw = json.loads((fixtures_dir / "openstates_bill_passed_house.json").read_text("utf-8"))
    bill = parse_bill(raw, session="2026rs")

    has_upper_action = any(
        ((a.get("organization") or {}).get("classification") == "upper")
        for a in raw.get("actions", [])
    )
    if has_upper_action:
        assert "ky-senate" in bill.body_ids
