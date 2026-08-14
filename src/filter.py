from __future__ import annotations

import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from src.paths import FIXTURES_DIR
from src.sources.base import Filing

Status = Literal["kill", "low", "candidate"]

# SPEC.md §4 — match category, subcategory, headline, and BSE detail text.
_KILL = [
    re.compile(p, re.I)
    for p in (
        r"trading\s*window",
        r"allotment of esop",
        r"\besop\b",
        r"\besps\b",
        r"employee stock",
        r"newspaper publication",
        r"publication of (the )?(un)?audited (financial )?results",
        r"record date",
        r"book clos",
        r"cut-?off date",
        r"investor complaint",
        r"statement of investor",
        r"loss of (share|certificate)",
        r"duplicate (share|certificate)",
        r"lost share",
        r"regulation\s*74",
        r"reg\.?\s*74",
        r"74\s*\(\s*5\s*\)",
        r"compliance certificate",
        r"secretarial compliance",
        r"reconciliation of share capital",
        r"proceeding(s)? of (the )?(agm|egm)",
        r"scrutinizer",
        r"newspaper advertisement",
        r"e-?voting",
        r"remote e-?voting",
        r"venue of (the )?(agm|egm)",
        r"registrar and (share )?transfer",
        r"certificate under reg",
    )
]

_LOW = [
    re.compile(p, re.I)
    for p in (
        r"analyst\s*/\s*investor\s+meet",
        r"analyst\s+meet",
        r"investor\s+meet(?!ing)",
        r"\bdividend\b",
        r"notice of (the )?(agm|egm|annual general meeting)",
        r"agm agenda",
        r"agenda of (the )?(agm|egm)",
        r"annual general meeting",
        r"extraordinary general meeting",
        r"extra[- ]ordinary general",
        r"incorporat(ion|ed).{0,40}subsidiar",
        r"subsidiar(y|ies) incorporat",
        r"change of rta",
        r"registrar and transfer agent",
    )
]


def _blob(filing: Filing) -> str:
    return " ".join(
        part
        for part in (
            filing.category,
            filing.subcategory,
            filing.headline,
            filing.detail,
        )
        if part
    )


def classify(filing: Filing) -> Status:
    blob = _blob(filing)
    if not blob.strip():
        return "candidate"
    for pat in _KILL:
        if pat.search(blob):
            return "kill"
    for pat in _LOW:
        if pat.search(blob):
            return "low"
    return "candidate"


def is_board_meeting_intimation(filing: Filing) -> bool:
    blob = _blob(filing).lower()
    if classify(filing) == "kill":
        return False
    if "outcome of board meeting" in blob:
        return False
    return "board meeting" in blob and "intimation" in blob


def is_results_or_ppt(filing: Filing) -> bool:
    blob = _blob(filing).lower()
    if classify(filing) != "candidate":
        return False
    if "newspaper" in blob:
        return False
    if filing.category.lower() == "result":
        return True
    if "financial results" in blob:
        return True
    if "investor presentation" in blob:
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
    blob = _blob(filing)
    for pat in _DATE_PATTERNS:
        match = pat.search(blob)
        if match:
            parsed = _parse_one_date(match.group(1))
            if parsed:
                return parsed
    return None


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    path = Path(args[0]) if args else FIXTURES_DIR / "anngetdata.json"
    if not path.exists():
        print(f"filter: missing fixture {path}", file=sys.stderr)
        return 1
    from src.sources.bse import load_fixture

    filings = load_fixture(path, "FIXTURE")
    counts: dict[str, int] = {"kill": 0, "low": 0, "candidate": 0}
    for filing in filings:
        status = classify(filing)
        counts[status] += 1
        print(f"{status:10} {filing.category}/{filing.subcategory}\t{filing.headline[:90]}")
    print(f"# {counts}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
