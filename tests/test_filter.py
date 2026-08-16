from src.filter import classify, is_board_meeting_intimation, is_results_or_ppt, parse_results_due
from src.sources.bse import load_fixture
from tests.helpers import filing

FIXTURE = "tests/fixtures/suzlon_real_50.json"


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
        ("Shareholder Meeting / Postal Ballot-Outcome of Postal_Ballot", "AGM/EGM", "Postal Ballot"),
    ]
    for headline, category, subcategory in cases:
        assert classify(filing(headline=headline, category=category, subcategory=subcategory)) == "kill", headline


def test_spec_low_list():
    cases = [
        ("Announcement under Regulation 30 (LODR)-Analyst / Investor Meet - Intimation", "Company Update", "Analyst / Investor Meet"),
        ("Dividend Intimation", "Corp. Action", "Dividend"),
        ("Notice of AGM", "AGM/EGM", "AGM"),
        ("Announcement under Regulation 30 (LODR)-Press Release / Media Release", "Company Update", "Press Release / Media Release"),
        ("Rumour verification - Regulation 30(11)", "Others", ""),
        ("Announcement under Regulation 30 (LODR)-Change in Management", "Company Update", "Change in Management", "Intimation of change in Senior Managerial Personnel"),
        ("Brand new category", "Mystery", ""),
        ("Announcement under Regulation 30 (LODR)-Award of Order", "Company Update", "Award of Order / Receipt of Order"),
    ]
    for row in cases:
        headline, category, subcategory, *rest = row
        detail = rest[0] if rest else ""
        assert classify(filing(headline=headline, category=category, subcategory=subcategory, detail=detail)) == "low", headline


def test_change_in_management_candidate_only_for_named_roles():
    low = filing(
        headline="Announcement under Regulation 30 (LODR)-Change in Management",
        category="Company Update",
        subcategory="Change in Management",
        detail="Cessation of Independent Director pursuant to completion of tenure.",
    )
    high = filing(
        headline="Announcement under Regulation 30 (LODR)-Change in Management",
        category="Company Update",
        subcategory="Change in Management",
        detail="Resignation of Director and appointment of CFO",
    )
    assert classify(low) == "low"
    assert classify(high) == "candidate"


def test_priority_sebi_order_on_general():
    row = filing(
        headline="SEBI Order No.WTM/SP/CFID/CFID_4/32427/2026-27 Dated 29Th May 2026",
        category="Company Update",
        subcategory="General",
        detail="Disclosure regarding penalty",
    )
    assert classify(row) == "priority"
    plain = filing(
        headline="Vesting Of Options Under Employee Stock Option Plan 2022",
        category="Company Update",
        subcategory="General",
    )
    assert classify(plain) == "candidate"


def test_spec_candidate_pairs():
    cases = [
        ("Board Meeting Intimation for unaudited financial results", "Board Meeting", "Board Meeting"),
        ("Outcome Of The Board Meeting Dated 28Th July 2026.", "Result", "Financial Results"),
        ("Board Meeting Outcome for Outcome Of The Board Meeting Dated 28Th July 2026.", "Board Meeting", "Outcome of Board Meeting"),
        ("Announcement under Regulation 30 (LODR)-Investor Presentation", "Company Update", "Investor Presentation"),
        ("Announcement under Regulation 30 (LODR)-Earnings Call Transcript", "Company Update", "Earnings Call Transcript"),
        ("Announcement under Regulation 30 (LODR)-Scheme of Arrangement", "Company Update", "Scheme of Arrangement"),
        ("Vesting Of Options Under Employee Stock Option Plan 2022", "Company Update", "General"),
    ]
    for headline, category, subcategory in cases:
        assert classify(filing(headline=headline, category=category, subcategory=subcategory)) == "candidate", headline


def test_unknown_is_low_not_candidate():
    assert classify(filing(headline="Brand new category", category="Mystery", subcategory="")) == "low"


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
