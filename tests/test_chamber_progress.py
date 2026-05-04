from scrapers.models import Action, derive_chamber_progress


def _action(classification, chamber="lower", date="2026-01-01"):
    return Action(date=date, description="", chamber=chamber, classification=classification)


def test_introduced_only():
    actions = [_action(["introduction"])]
    assert derive_chamber_progress(actions) == {
        "lower": "introduced",
        "upper": None,
        "governor": None,
    }


def test_referred_to_committee():
    actions = [
        _action(["introduction"]),
        _action(["referral-committee"]),
    ]
    assert derive_chamber_progress(actions)["lower"] == "in_committee"


def test_committee_passage():
    actions = [
        _action(["introduction"]),
        _action(["committee-passage-favorable"]),
    ]
    assert derive_chamber_progress(actions)["lower"] == "passed_committee"


def test_passed_lower_then_referred_upper():
    actions = [
        _action(["introduction"], chamber="lower"),
        _action(["passage"], chamber="lower"),
        _action(["referral-committee"], chamber="upper"),
    ]
    cp = derive_chamber_progress(actions)
    assert cp["lower"] == "passed"
    assert cp["upper"] == "in_committee"


def test_governor_signature():
    actions = [
        _action(["passage"], chamber="lower"),
        _action(["passage"], chamber="upper"),
        _action(["executive-signature"], chamber=None),
    ]
    cp = derive_chamber_progress(actions)
    assert cp["lower"] == "passed"
    assert cp["upper"] == "passed"
    assert cp["governor"] == "signed"


def test_governor_veto():
    actions = [
        _action(["passage"], chamber="lower"),
        _action(["passage"], chamber="upper"),
        _action(["executive-veto"], chamber=None),
    ]
    assert derive_chamber_progress(actions)["governor"] == "vetoed"


def test_progress_is_monotonic():
    actions = [
        _action(["passage"], chamber="lower"),
        _action(["referral-committee"], chamber="lower"),  # recommit
    ]
    assert derive_chamber_progress(actions)["lower"] == "passed"


def test_failure_recorded():
    actions = [
        _action(["introduction"]),
        _action(["failure"]),
    ]
    assert derive_chamber_progress(actions)["lower"] == "failed"
