from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from src.ledger import LedgerError, Ticker, by_symbol, load_tickers
from src.paths import FIXTURES_DIR
from src.sources.base import Filing, Source

IST = ZoneInfo("Asia/Kolkata")
# BSE's announcements page still uses this JSON Table shape. AnnGetData/w
# now returns the string "No Record Found!"; the live endpoint is SubCategory.
ANN_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
HOME_URL = "https://www.bseindia.com/corporates/ann.html"
PDF_LIVE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
PDF_HIS = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.bseindia.com",
    "Referer": "https://www.bseindia.com/",
    "X-Requested-With": "XMLHttpRequest",
}

MAX_PAGES = 20
TIMEOUT = 25


def _parse_dt(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt


def _pdf_url(row: dict[str, Any]) -> str | None:
    name = str(row.get("ATTACHMENTNAME") or "").strip()
    if not name:
        nsurl = str(row.get("NSURL") or "").strip()
        return nsurl or None
    if name.lower().startswith("http"):
        return name
    filed = _parse_dt(row.get("DissemDT") or row.get("NEWS_DT") or row.get("DT_TM"))
    base = PDF_HIS
    if filed is not None and datetime.now(tz=IST) - filed.astimezone(IST) <= timedelta(days=7):
        base = PDF_LIVE
    return base + name


def _ann_id(row: dict[str, Any]) -> str | None:
    for key in ("NEWSID", "NEWS_ID", "newsid"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _headline(row: dict[str, Any]) -> str:
    for key in ("NEWSSUB", "HEADLINE", "MORE"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def parse_anngetdata(payload: dict[str, Any], ticker: str) -> list[Filing]:
    rows = payload.get("Table") or []
    filings: list[Filing] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ann_id = _ann_id(row)
        pdf_url = _pdf_url(row)
        if not ann_id and not pdf_url:
            continue
        headline = _headline(row)
        extra_bits = []
        for key in ("HEADLINE", "MORE"):
            value = str(row.get(key) or "").strip()
            if value and value not in headline and value not in extra_bits:
                extra_bits.append(value)
        filings.append(
            Filing(
                ticker=ticker,
                exchange="BSE",
                ann_id=ann_id,
                category=str(row.get("CATEGORYNAME") or "").strip(),
                subcategory=str(row.get("SUBCATNAME") or "").strip(),
                headline=headline,
                pdf_url=pdf_url,
                filed_at=_parse_dt(
                    row.get("DissemDT") or row.get("NEWS_DT") or row.get("DT_TM")
                ),
                detail=" ".join(extra_bits),
            )
        )
    return filings


def load_fixture(path: Path | str, ticker: str) -> list[Filing]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not an AnnGetData object")
    return parse_anngetdata(payload, ticker)


class BSESource(Source):
    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._session.headers.update(HEADERS)
        self._warmed = False

    def _warm(self) -> None:
        if self._warmed:
            return
        try:
            self._session.get(HOME_URL, timeout=TIMEOUT)
        except requests.RequestException:
            pass
        self._warmed = True

    def fetch(self, ticker: Ticker, since: datetime) -> list[Filing]:
        self._warm()
        since_ist = since.astimezone(IST) if since.tzinfo else since.replace(tzinfo=IST)
        today = datetime.now(tz=IST).date()
        start = since_ist.date()
        if start > today:
            return []
        collected: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            params = {
                "pageno": page,
                "strCat": "-1",
                "strPrevDate": start.strftime("%Y%m%d"),
                "strScrip": ticker.bse_code,
                "strSearch": "P",
                "strToDate": today.strftime("%Y%m%d"),
                "strType": "C",
                "subcategory": "",
            }
            response = self._session.get(ANN_URL, params=params, timeout=TIMEOUT)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                break
            rows = payload.get("Table") or []
            if not rows:
                break
            collected.extend(row for row in rows if isinstance(row, dict))
            total = 0
            table1 = payload.get("Table1") or []
            if table1 and isinstance(table1[0], dict):
                try:
                    total = int(table1[0].get("ROWCNT") or 0)
                except (TypeError, ValueError):
                    total = 0
            if total and len(collected) >= total:
                break
            if len(rows) < 50:
                break
        merged = {"Table": collected}
        filings = parse_anngetdata(merged, ticker.symbol)
        cutoff = since_ist
        out: list[Filing] = []
        for filing in filings:
            if filing.filed_at is None or filing.filed_at.astimezone(IST) >= cutoff:
                out.append(filing)
        return out

    def fetch_raw_page(
        self, ticker: Ticker, since: datetime, page: int = 1
    ) -> dict[str, Any]:
        """One AnnGetData JSON page — used to save fixtures."""
        self._warm()
        since_ist = since.astimezone(IST) if since.tzinfo else since.replace(tzinfo=IST)
        today = datetime.now(tz=IST).date()
        params = {
            "pageno": page,
            "strCat": "-1",
            "strPrevDate": since_ist.date().strftime("%Y%m%d"),
            "strScrip": ticker.bse_code,
            "strSearch": "P",
            "strToDate": today.strftime("%Y%m%d"),
            "strType": "C",
            "subcategory": "",
        }
        response = self._session.get(ANN_URL, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"AnnGetData-shaped JSON missing; got {payload!r:.80}")
        return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch BSE announcements for a ledger name")
    parser.add_argument("symbol", help="ledger symbol or BSE scrip code")
    parser.add_argument("--days", type=int, default=14, help="lookback days (default 14)")
    parser.add_argument(
        "--save-fixture",
        nargs="?",
        const="anngetdata.json",
        help="write one real AnnGetData page under tests/fixtures/",
    )
    args = parser.parse_args(argv)
    try:
        tickers = load_tickers()
        ticker = by_symbol(tickers, args.symbol)
    except LedgerError as exc:
        print(f"bse: {exc}", file=sys.stderr)
        return 1
    since = datetime.now(tz=IST) - timedelta(days=args.days)
    source = BSESource()
    if args.save_fixture:
        FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
        dest = Path(args.save_fixture)
        if not dest.is_absolute():
            dest = FIXTURES_DIR / dest.name
        payload = source.fetch_raw_page(ticker, since, page=1)
        dest.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        n = len(payload.get("Table") or [])
        print(f"saved {n} rows to {dest}")
        return 0 if n else 1
    try:
        filings = source.fetch(ticker, since)
    except requests.RequestException as exc:
        print(f"bse: fetch failed: {exc}", file=sys.stderr)
        return 1
    if not filings:
        print(f"no filings for {ticker.symbol} since {since.date()}")
        return 0
    for f in filings:
        when = f.filed_at.astimezone(IST).isoformat(timespec="minutes") if f.filed_at else ""
        cat = f.category or "-"
        sub = f.subcategory or "-"
        print(f"{when}\t{cat}/{sub}\t{f.headline}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
