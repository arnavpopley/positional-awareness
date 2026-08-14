from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.filter import classify, is_board_meeting_intimation, is_results_or_ppt, parse_results_due
from src.ledger import LedgerError, Ticker, load_tickers
from src.notify import CHANNEL, notify_candidate
from src.schedule import IST, MIN_INTERVAL, tickers_for_slot
from src.sources.base import Filing
from src.sources.bse import BSESource, load_fixture
from src.store import Store

LOOKBACK_DAYS = 14
GAP_BETWEEN_NAMES = 0.5


def ingest(
    filings: list[Filing],
    store: Store,
    *,
    notify: bool,
    notifier=notify_candidate,
) -> dict[str, int]:
    stats = {"kill": 0, "low": 0, "candidate": 0, "dup": 0, "notified": 0}
    for filing in filings:
        status = classify(filing)
        row_id = store.insert_filing(filing, status)
        if row_id is None:
            stats["dup"] += 1
            continue
        stats[status] += 1
        if is_board_meeting_intimation(filing):
            due = parse_results_due(filing)
            if due:
                store.set_results_due(filing.ticker, due)
        if is_results_or_ppt(filing):
            store.mark_results_filed(
                filing.ticker, parse_results_due(filing) or store.results_due(filing.ticker)
            )
        if notify and status == "candidate" and not store.alert_sent(row_id, CHANNEL):
            if notifier(filing):
                store.record_alert(row_id, CHANNEL)
                stats["notified"] += 1
    return stats


def _since(store: Store, ticker: Ticker, now: datetime) -> datetime:
    last = store.last_fetch_at(ticker.symbol)
    floor = now - timedelta(days=LOOKBACK_DAYS)
    if last is None:
        return floor
    last_aware = last if last.tzinfo else last.replace(tzinfo=IST)
    return max(floor, last_aware - timedelta(hours=1))


def poll_tickers(
    tickers: list[Ticker],
    store: Store,
    source: BSESource,
    *,
    notify: bool,
    now: datetime | None = None,
) -> dict[str, int]:
    import time as time_mod

    ist = now or datetime.now(tz=IST)
    totals = {"kill": 0, "low": 0, "candidate": 0, "dup": 0, "notified": 0}
    for i, ticker in enumerate(tickers):
        if i:
            time_mod.sleep(GAP_BETWEEN_NAMES)
        try:
            filings = source.fetch(ticker, _since(store, ticker, ist))
        except requests.RequestException as exc:
            print(f"poll: {ticker.symbol} fetch failed: {exc}", file=sys.stderr)
            continue
        stats = ingest(filings, store, notify=notify)
        store.touch_fetch(ticker.symbol, ist)
        for key in totals:
            totals[key] += stats[key]
        print(
            f"{ticker.symbol}: +{stats['candidate']} candidate "
            f"+{stats['low']} low +{stats['kill']} kill "
            f"dup={stats['dup']} notified={stats['notified']}"
        )
    return totals


def poll_fixture(
    path: Path,
    tickers: list[Ticker],
    store: Store,
    *,
    notify: bool,
    notifier=notify_candidate,
) -> dict[str, int]:
    totals = {"kill": 0, "low": 0, "candidate": 0, "dup": 0, "notified": 0}
    for ticker in tickers:
        filings = load_fixture(path, ticker.symbol)
        stats = ingest(filings, store, notify=notify, notifier=notifier)
        store.touch_fetch(ticker.symbol, datetime.now(tz=IST))
        for key in totals:
            totals[key] += stats[key]
    return totals


def run_slot(kind: str, *, notify_backfill: bool = False, fixture: Path | None = None) -> None:
    tickers = load_tickers()
    store = Store()
    try:
        due = tickers_for_slot(tickers, store, kind=kind)
        if not due:
            return
        first = store.filing_count() == 0
        notify = notify_backfill or not first
        if fixture:
            stats = poll_fixture(fixture, due, store, notify=notify)
        else:
            stats = poll_tickers(due, store, BSESource(), notify=notify)
        print(
            f"slot={kind} names={len(due)} "
            f"candidate={stats['candidate']} kill={stats['kill']} "
            f"low={stats['low']} notified={stats['notified']}"
        )
    finally:
        store.close()


def run_scheduler() -> None:
    scheduler = BlockingScheduler(timezone=IST)
    scheduler.add_job(
        run_slot,
        CronTrigger(hour=8, minute=0, timezone=IST),
        kwargs={"kind": "ordinary"},
        id="slot-0800",
        max_instances=1,
        coalesce=True,
    )
    for hour, minute in ((9, 30), (12, 30), (16, 0), (19, 0)):
        scheduler.add_job(
            run_slot,
            CronTrigger(
                day_of_week="mon-fri",
                hour=hour,
                minute=minute,
                timezone=IST,
            ),
            kwargs={"kind": "ordinary"},
            id=f"slot-{hour:02d}{minute:02d}",
            max_instances=1,
            coalesce=True,
        )
    scheduler.add_job(
        run_slot,
        IntervalTrigger(minutes=int(MIN_INTERVAL.total_seconds() // 60), timezone=IST),
        kwargs={"kind": "interval"},
        id="interval-15",
        max_instances=1,
        coalesce=True,
    )
    print(
        "scheduler: ordinary 09:30/12:30/16:00/19:00 IST weekdays; "
        "08:00 IST daily; 15 min floor for results-week/morning"
    )
    scheduler.start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Poll BSE filings on the SPEC cadence")
    parser.add_argument("--once", action="store_true", help="one ordinary pass, then exit")
    parser.add_argument(
        "--fixture",
        type=Path,
        help="classify a saved AnnGetData JSON instead of calling BSE",
    )
    parser.add_argument(
        "--notify-backfill",
        action="store_true",
        help="notify candidate filings even on an empty database",
    )
    args = parser.parse_args(argv)
    try:
        load_tickers()
    except LedgerError as exc:
        print(f"main: {exc}", file=sys.stderr)
        return 1
    try:
        if args.once:
            run_slot(
                "ordinary",
                notify_backfill=args.notify_backfill,
                fixture=args.fixture,
            )
            return 0
        if args.fixture:
            print("main: --fixture is for --once", file=sys.stderr)
            return 2
        run_scheduler()
        return 0
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
