from src.filter import classify, is_board_meeting_intimation, is_results_or_ppt, parse_results_due
from src.sources.bse import load_fixture
from tests.helpers import filing

FIXTURE = "tests/fixtures/anngetdata.json"


def test_spec_kill_list():
    cases = [
        ("Closure of Trading Window", "Insider Trading / SAST", "Closure of Trading Window"),
        ("Announcement under Regulation 30 (LODR)-Allotment of ESOP / ESPS", "Company Update", "Allotment of ESOP / ESPS"),
        ("Intimation Of Book Closure And Cut-Off Date.", "Corp. Action", "Book Closure"),
        ("Compliances-Certificate under Reg. 74 (5) of SEBI (DP) Regulations, 2018", "Company Update", "Certificate under Reg. 74 (5) of SEBI (DP) Regulations, 2018"),
        ("Newspaper Publication of Financial Results", "Company Update", "Newspaper Publication"),
        ("Record Date Intimation", "Corp. Action", "Record Date"),
        ("Statement of Investor Complaints", "Company Update", "Investor Complaints / Information"),
        ("Loss of Share Certificate", "Company Update", "Loss of Share Certificates"),
        ("Proceedings of the AGM", "AGM/EGM", "AGM"),
    ]
    for headline, category, subcategory in cases:
        assert classify(filing(headline=headline, category=category, subcategory=subcategory)) == "kill", headline


def test_spec_low_list():
    cases = [
        ("Announcement under Regulation 30 (LODR)-Analyst / Investor Meet - Intimation", "Company Update", "Analyst / Investor Meet"),
        ("Dividend Intimation", "Corp. Action", "Dividend"),
        ("Notice of AGM", "AGM/EGM", "AGM"),
        ("Incorporation of a Wholly Owned Subsidiary", "Company Update", "General"),
    ]
    for headline, category, subcategory in cases:
        assert classify(filing(headline=headline, category=category, subcategory=subcategory)) == "low", headline


def test_spec_candidate_and_unknown():
    cases = [
        ("Board Meeting Intimation for unaudited financial results", "Board Meeting", "Board Meeting"),
        ("Outcome Of The Board Meeting Dated 28Th July 2026.", "Result", "Financial Results"),
        ("Announcement under Regulation 30 (LODR)-Investor Presentation", "Company Update", "Investor Presentation"),
        ("Announcement under Regulation 30 (LODR)-Earnings Call Transcript", "Company Update", "Earnings Call Transcript"),
        ("Announcement under Regulation 30 (LODR)-Award of Order", "Company Update", "Award of Order / Receipt of Order"),
        ("Credit Rating", "Company Update", "Credit Rating"),
        ("Change in Management", "Company Update", "Change in Management"),
        ("Scheme of Arrangement", "Company Update", "Scheme of Arrangement"),
        ("Something we have never seen", "Company Update", "General"),
        ("Brand new category", "Mystery", ""),
    ]
    for headline, category, subcategory in cases:
        assert classify(filing(headline=headline, category=category, subcategory=subcategory)) == "candidate", headline


def test_fixture_trading_window_is_kill():
    hits = [
        f
        for f in load_fixture(FIXTURE, "SUZLON")
        if "trading window" in (f.subcategory or "").lower()
    ]
    assert hits
    assert all(classify(f) == "kill" for f in hits)


def test_fixture_board_meeting_and_results_are_candidates():
    filings = load_fixture(FIXTURE, "SUZLON")
    boards = [f for f in filings if f.subcategory == "Board Meeting"]
    results = [f for f in filings if f.subcategory == "Financial Results"]
    assert boards and results
    assert all(classify(f) == "candidate" for f in boards + results)
    assert any(is_board_meeting_intimation(f) for f in boards)
    assert any(is_results_or_ppt(f) for f in results)


def test_parse_results_due_from_bse_intimation_detail():
    filings = load_fixture(FIXTURE, "SUZLON")
    intimations = [f for f in filings if is_board_meeting_intimation(f)]
    dues = [parse_results_due(f) for f in intimations]
    assert any(d and d.isoformat() == "2026-07-28" for d in dues)
