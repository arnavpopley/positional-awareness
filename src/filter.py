from __future__ import annotations

import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from src.paths import FIXTURES_DIR
from src.sources.base import Filing

IST = ZoneInfo("Asia/Kolkata")

Status = Literal["kill", "low", "candidate", "priority"]

NOTIFY_MAX_AGE = timedelta(hours=48)

KILL_PAIRS = {
    ("Insider Trading / SAST", "Closure of Trading Window"),
    ("Company Update", "Allotment of ESOP / ESPS"),
    ("Corp. Action", "Book Closure"),
    ("Corp. Action", "Record Date"),
    ("Company Update", "Newspaper Publication"),
    (
        "Company Update",
        "Certificate under Reg. 74 (5) of SEBI (DP) Regulations, 2018",
    ),
    ("Company Update", "Reg.24(A)-Annual Secretarial Compliance"),
    ("Company Update", "Investor Complaints / Information"),
    ("Company Update", "Loss of Share Certificates"),
    ("AGM/EGM", "Postal Ballot"),
}

LOW_PAIRS = {
    ("Company Update", "Analyst / Investor Meet"),
    ("Company Update", "Press Release / Media Release"),
    ("Corp. Action", "Dividend"),
    ("Others", ""),
    ("Others", "Rumour verification"),
}

CANDIDATE_PAIRS = {
    ("Board Meeting", "Board Meeting"),
    ("Board Meeting", "Outcome of Board Meeting"),
    ("Result", "Financial Results"),
    ("Company Update", "Earnings Call Transcript"),
    ("Company Update", "Investor Presentation"),
    ("Company Update", "Scheme of Arrangement"),
    ("Company Update", "General"),
}

_PRIORITY_HEAD = re.compile(
    r"sebi\s+order|\badjudication\b|\bshow\s+cause\b|\bpenalty\b",
    re.I,
)
_RUMOUR_HEAD = re.compile(r"rumour\s+verification|regulation\s*30\s*\(\s*11\s*\)", re.I)
_CIM_CANDIDATE = re.compile(
    r"managing\s+director|\bMD\b|chief\s+executive|\bCEO\b|"
    r"chief\s+financial|\bCFO\b|whole-?time\s+director|"
    r"\bauditor\b|resignation of director",
    re.I,
)
_KILL_HEADLINE = [
    re.compile(p, re.I)
    for p in (
        r"trading\s*window",
        r"newspaper publication",
        r"publication of (the )?(un)?audited (financial )?results",
        r"record date",
        r"book clos",
        r"investor complaint",
        r"loss of (share|certificate)",
        r"duplicate (share|certificate)",
        r"lost share",
        r"regulation\s*74",
        r"74\s*\(\s*5\s*\)",
        r"compliance certificate",
        r"secretarial compliance",
        r"proceeding(s)? of (the )?(agm|egm)",
        r"scrutinizer",
    )
]


def _norm(value: str | None) -> str:
    return (value or "").strip()


def _pair(filing: Filing) -> tuple[str, str]:
    return (_norm(filing.category), _norm(filing.subcategory))


def _title(filing: Filing) -> str:
    return " ".join(part for part in (filing.headline, filing.detail) if part)


def classify(filing: Filing) -> Status:
    pair = _pair(filing)
    title = _title(filing)

    if pair == ("Company Update", "General") and _PRIORITY_HEAD.search(title):
        return "priority"

    if pair in KILL_PAIRS:
        return "kill"

    if pair not in CANDIDATE_PAIRS and pair != ("Company Update", "Change in Management"):
        for pat in _KILL_HEADLINE:
            if pat.search(title) or pat.search(" ".join(pair)):
                return "kill"

    if _RUMOUR_HEAD.search(title) or pair in {("Others", "Rumour verification")}:
        return "low"

    if pair in LOW_PAIRS:
        return "low"

    if pair == ("Company Update", "Change in Management"):
        return "candidate" if _CIM_CANDIDATE.search(title) else "low"

    if pair in CANDIDATE_PAIRS:
        return "candidate"

    return "low"


def is_notify_fresh(filing: Filing, now: datetime) -> bool:
    """Never notify on a filing older than 48 hours at poll time."""
    if filing.filed_at is None:
        return False
    filed = filing.filed_at
    if filed.tzinfo is None:
        filed = filed.replace(tzinfo=IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    return now - filed.astimezone(now.tzinfo) <= NOTIFY_MAX_AGE


def is_board_meeting_intimation(filing: Filing) -> bool:
    if classify(filing) == "kill":
        return False
    cat, sub = _pair(filing)
    return cat == "Board Meeting" and sub == "Board Meeting"


def is_board_meeting_outcome(filing: Filing) -> bool:
    cat, sub = _pair(filing)
    return cat == "Board Meeting" and sub == "Outcome of Board Meeting"


def is_financial_results(filing: Filing) -> bool:
    cat, sub = _pair(filing)
    return cat == "Result" and sub == "Financial Results"


def is_results_or_ppt(filing: Filing) -> bool:
    if classify(filing) not in ("candidate", "priority"):
        return False
    cat, sub = _pair(filing)
    if cat == "Result" or sub == "Financial Results":
        return True
    if sub == "Investor Presentation":
        return True
    return False


_DATE_PATTERNS = [
    re.compile(r"scheduled on\s+(\d{1,2}/\d{1,2}/\d{4})", re.I),
    re.compile(r"scheduled on\s+(\d{1,2}-\d{1,2}-\d{4})", re.I),
    re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b"),
    re.compile(r"\b(\d{1,2}-\d{1,2}-\d{4})\b"),
    re.compile(
        r"(\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
        r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{4})",
        re.I,
    ),
]


def _parse_one_date(text: str) -> date | None:
    raw = re.sub(r"(st|nd|rd|th)\b", "", text.strip(), flags=re.I)
    raw = raw.replace(".", "").replace("  ", " ").strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_results_due(filing: Filing) -> date | None:
    blob = " ".join(part for part in (_pair(filing) + (_title(filing),)) if part)
    for pat in _DATE_PATTERNS:
        match = pat.search(blob)
        if match:
            parsed = _parse_one_date(match.group(1))
            if parsed:
                return parsed
    return None


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    path = Path(args[0]) if args else FIXTURES_DIR / "suzlon_real_50.json"
    if not path.exists():
        print(f"filter: missing fixture {path}", file=sys.stderr)
        return 1
    from src.sources.bse import load_fixture

    filings = load_fixture(path, "FIXTURE")
    counts: dict[str, int] = {"kill": 0, "low": 0, "candidate": 0, "priority": 0}
    for filing in filings:
        status = classify(filing)
        counts[status] += 1
        print(f"{status:10} {filing.category}/{filing.subcategory}\t{filing.headline[:90]}")
    print(f"# {counts}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
