"""Tests for people parsing + sponsor/voter person_id capture."""

import json

from scrapers.openstates import (
    parse_bill,
    parse_person,
    person_slug_for_ky,
    slugify_person_name,
)


def test_parse_person_legislator(fixtures_dir):
    raw = json.loads((fixtures_dir / "openstates_people.json").read_text("utf-8"))
    wheeler = next(r for r in raw["results"] if r["name"] == "Phillip Wheeler")
    p = parse_person(wheeler)

    assert p is not None
    assert p.id == "ky-phillip-wheeler"
    assert p.source == "openstates"
    assert p.source_id == wheeler["id"]
    assert p.body_id == "ky-senate"
    assert p.chamber == "upper"
    assert p.party == "Republican"
    assert p.district == "31"
    assert p.photo_url == "https://data.openstates.org/images/wheeler.jpg"
    assert "phillip.wheeler@lrc.ky.gov" in p.contact["emails"]
    assert any("Frankfort" in a["address"] for a in p.contact["addresses"])
    assert any("openstates.org" in s for s in p.sources)
    assert p.active is True


def test_parse_person_skips_non_legislator(fixtures_dir):
    raw = json.loads((fixtures_dir / "openstates_people.json").read_text("utf-8"))
    governor = next(r for r in raw["results"] if r["name"] == "Andy Beshear")
    assert parse_person(governor) is None


def test_parse_person_handles_minimal_record(fixtures_dir):
    raw = json.loads((fixtures_dir / "openstates_people.json").read_text("utf-8"))
    madon = next(r for r in raw["results"] if r["name"] == "Scott Madon")
    p = parse_person(madon)

    assert p is not None
    assert p.id == "ky-scott-madon"
    assert p.body_id == "ky-senate"
    assert p.photo_url is None
    assert p.contact["emails"] == []
    assert p.contact["addresses"] == []


def test_slug_helpers():
    assert slugify_person_name("Phillip Wheeler") == "phillip-wheeler"
    assert slugify_person_name("M. O'Brien-Smith") == "m-o-brien-smith"
    assert person_slug_for_ky("Phillip Wheeler") == "ky-phillip-wheeler"
    assert person_slug_for_ky("") == ""


def test_sponsor_carries_person_id(fixtures_dir):
    raw = json.loads((fixtures_dir / "openstates_bill_passed_house.json").read_text("utf-8"))
    bill = parse_bill(raw, session="2026rs")

    sponsors_with_id = [s for s in bill.sponsors if s.person_id]
    assert sponsors_with_id, "expected at least one sponsor to have a person_id"
    for s in sponsors_with_id:
        assert s.person_id.startswith("ocd-person/")


def test_member_vote_carries_person_id(fixtures_dir):
    raw = json.loads((fixtures_dir / "openstates_bill_passed_house.json").read_text("utf-8"))
    bill = parse_bill(raw, session="2026rs")

    member_votes = [mv for v in bill.votes for mv in v.member_votes]
    with_id = [mv for mv in member_votes if mv.person_id]
    assert with_id, "expected member_votes to carry person_id"
    for mv in with_id:
        assert mv.person_id.startswith("ocd-person/")
