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
