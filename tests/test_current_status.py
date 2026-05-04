from scrapers.models import chamber_progress_to_status


def test_signed_by_governor():
    cp = {"lower": "passed", "upper": "passed", "governor": "signed"}
    assert chamber_progress_to_status(cp) == "Signed by governor"


def test_vetoed():
    cp = {"lower": "passed", "upper": "passed", "governor": "vetoed"}
    assert chamber_progress_to_status(cp) == "Vetoed by governor"


def test_passed_house_in_senate_committee():
    cp = {"lower": "passed", "upper": "in_committee", "governor": None}
    assert chamber_progress_to_status(cp) == "Passed House, in Senate committee"


def test_introduced_in_house():
    cp = {"lower": "introduced", "upper": None, "governor": None}
    assert chamber_progress_to_status(cp) == "Introduced in House"


def test_introduced_in_senate():
    cp = {"lower": None, "upper": "introduced", "governor": None}
    assert chamber_progress_to_status(cp) == "Introduced in Senate"


def test_passed_both_chambers_pending_governor():
    cp = {"lower": "passed", "upper": "passed", "governor": None}
    assert chamber_progress_to_status(cp) == "Passed House and Senate"


def test_failed_in_house():
    cp = {"lower": "failed", "upper": None, "governor": None}
    assert chamber_progress_to_status(cp) == "Failed in House"
