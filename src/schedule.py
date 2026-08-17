from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from src.ledger import Ticker
from src.store import Store

IST = ZoneInfo("Asia/Kolkata")

ORDINARY_WEEKDAY = ((9, 30), (12, 30), (16, 0), (19, 0))
MORNING_SLOT = (8, 0)
MIN_INTERVAL = timedelta(minutes=15)
RESULTS_WEEK_INTERVAL = timedelta(minutes=20)
RESULTS_WEEK_DAYS = 5


def now_ist(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(tz=IST)
    if now.tzinfo is None:
        return now.replace(tzinfo=IST)
    return now.astimezone(IST)


def _due_date(ticker: Ticker, store: Store) -> date | None:
    stored = store.results_due(ticker.symbol)
    if stored:
        return stored
    return ticker.results_due


def _results_still_pending(ticker: Ticker, store: Store, due: date) -> bool:
    filed = store.results_filed_for(ticker.symbol)
    return filed != due


def tickers_for_slot(
    tickers: list[Ticker],
    store: Store,
    *,
    kind: str,
    now: datetime | None = None,
) -> list[Ticker]:
    """kind is 'ordinary' (fixed IST slots) or 'interval' (results week/morning)."""
    ist = now_ist(now)
    tickers = [t for t in tickers if t.polls()]
    chosen: list[Ticker] = []
    if kind == "ordinary":
        candidates = list(tickers)
    elif kind == "interval":
        if ist.weekday() >= 5:
            return []
        if not (time(8, 0) <= ist.time() <= time(19, 0)):
            return []
        for ticker in tickers:
            due = _due_date(ticker, store)
            if due is None:
                continue
            days = (due - ist.date()).days
            if days < 0 or days > RESULTS_WEEK_DAYS:
                continue
            if not _results_still_pending(ticker, store, due):
                continue
            chosen.append(ticker)
        candidates = chosen
    else:
        raise ValueError(f"unknown slot kind {kind}")

    ready: list[Ticker] = []
    for ticker in candidates:
        last = store.last_fetch_at(ticker.symbol)
        if last is not None:
            last_ist = last if last.tzinfo else last.replace(tzinfo=IST)
            elapsed = ist - last_ist.astimezone(IST)
            if elapsed < MIN_INTERVAL:
                continue
            due = _due_date(ticker, store)
            morning = (
                due == ist.date()
                and due is not None
                and _results_still_pending(ticker, store, due)
            )
            if kind == "interval" and not morning and elapsed < RESULTS_WEEK_INTERVAL:
                continue
        ready.append(ticker)
    return ready
