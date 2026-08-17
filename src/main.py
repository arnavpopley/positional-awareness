from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.filter import (
    classify,
    is_board_meeting_intimation,
    is_notify_fresh,
    is_results_or_ppt,
    parse_results_due,
)
from src.ledger import LedgerError, Ticker, load_tickers
from src.notify import CHANNEL, notify_candidate
from src.pack import deliver_packs, deliver_weekly_nudge
from src.schedule import IST, MIN_INTERVAL, tickers_for_slot
from src.sources.base import Filing
from src.sources.bse import BSESource, load_fixture
from src.store import Store

LOOKBACK_DAYS = 14
GAP_BETWEEN_NAMES = 0.5
PUSH_STATUSES = {"candidate", "priority"}


def _empty_stats() -> dict[str, int]:
    return {
        "kill": 0,
        "low": 0,
        "candidate": 0,
        "priority": 0,
        "dup": 0,
        "notified": 0,
        "collapsed": 0,
        "extracted": 0,
        "extract_cached": 0,
        "needs_manual_read": 0,
        "scored": 0,
    }


def ingest(
    filings: list[Filing],
    store: Store,
    *,
    notify: bool,
    notifier=notify_candidate,
    now: datetime | None = None,
    tickers: list[Ticker] | None = None,
    extractor=None,
    scorer=None,
) -> dict[str, int]:
    """Store every filing. Notify only fresh candidate/priority rows.

    Recency (48h) is independent of DB emptiness and of --notify-backfill.
    Priority always notifies when fresh (no digest/batching skip).
    Extraction runs only for fresh, non-collapsed candidate/priority rows.
    """
    from src.extract import extract_filing as default_extract
    from src.score import persist, score_extraction

    now = now or datetime.now(tz=IST)
    stats = _empty_stats()
    inserted: list[tuple[Filing, str, int]] = []
    tickers_seen: set[str] = set()
    book = {t.symbol: t for t in (tickers or [])}
    peer_list = list(tickers or [])
    do_extract = default_extract if extractor is None else extractor
    do_score = score_extraction if scorer is None else scorer
    for filing in filings:
        status = classify(filing)
        row_id = store.insert_filing(filing, status)
        if row_id is None:
            stats["dup"] += 1
            continue
        stats[status] += 1
        tickers_seen.add(filing.ticker)
        if is_board_meeting_intimation(filing):
            due = parse_results_due(filing)
            if due:
                store.set_results_due(filing.ticker, due)
        if is_results_or_ppt(filing):
            store.mark_results_filed(
                filing.ticker, parse_results_due(filing) or store.results_due(filing.ticker)
            )
        inserted.append((filing, status, row_id))

    suppressed: set[int] = set()
    for symbol in tickers_seen:
        suppressed |= store.collapse_outcome_into_results(symbol)
    stats["collapsed"] = len(suppressed)

    for filing, status, row_id in inserted:
        if row_id in suppressed:
            continue
        if status not in PUSH_STATUSES:
            continue
        if not is_notify_fresh(filing, now):
            continue
        row_ticker = book.get(filing.ticker)
        if row_ticker is not None and not row_ticker.polls():
            continue
        exiting = row_ticker is not None and row_ticker.status == "exiting"
        if exiting and not (
            is_board_meeting_intimation(filing) or is_results_or_ppt(filing)
        ):
            continue
        scoreable = row_ticker is None or row_ticker.scores()
        result = do_extract(filing, row_ticker, store) if scoreable else None
        scored = None
        manual = False
        if result is not None:
            stats["extracted"] += 1
            if getattr(result, "cached", False):
                stats["extract_cached"] += 1
            manual = bool(getattr(result, "needs_manual_read", False))
            if manual:
                stats["needs_manual_read"] += 1
            payload = getattr(result, "kpis_json", None)
            scored = do_score(
                payload,
                ticker=row_ticker,
                peers=peer_list,
                store=store,
                needs_manual_read=manual,
                filing_id=row_id,
            )
            if scored is not None:
                persist(
                    scored,
                    store,
                    filing_id=row_id,
                    triage={"needs_manual_read": manual},
                )
                stats["scored"] += 1
                print(f"{filing.ticker}: {scored.display()}")
        if not notify:
            continue
        if store.alert_sent(row_id, CHANNEL):
            continue
        notified = False
        try:
            notified = notifier(
                filing,
                status=status,
                band=None if scored is None else scored.band,
                needs_manual_read=manual,
            )
        except TypeError:
            notified = notifier(filing, status=status)
        if notified:
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
    totals = _empty_stats()
    for i, ticker in enumerate(tickers):
        if i:
            time_mod.sleep(GAP_BETWEEN_NAMES)
        try:
            filings = source.fetch(ticker, _since(store, ticker, ist))
        except requests.RequestException as exc:
            print(f"poll: {ticker.symbol} fetch failed: {exc}", file=sys.stderr)
            continue
        stats = ingest(filings, store, notify=notify, now=ist, tickers=tickers)
        store.touch_fetch(ticker.symbol, ist)
        for key in totals:
            totals[key] += stats[key]
        print(
            f"{ticker.symbol}: +{stats['candidate']} candidate "
            f"+{stats['priority']} priority +{stats['low']} low "
            f"+{stats['kill']} kill dup={stats['dup']} "
            f"notified={stats['notified']} collapsed={stats['collapsed']} "
            f"extracted={stats['extracted']} scored={stats['scored']}"
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
    totals = _empty_stats()
    ist = datetime.now(tz=IST)
    for ticker in tickers:
        filings = load_fixture(path, ticker.symbol)
        stats = ingest(filings, store, notify=notify, notifier=notifier, now=ist, tickers=tickers)
        store.touch_fetch(ticker.symbol, ist)
        for key in totals:
            totals[key] += stats[key]
    return totals


def run_slot(
    kind: str,
    *,
    notify_backfill: bool = False,
    fixture: Path | None = None,
    now: datetime | None = None,
) -> None:
    tickers = load_tickers()
    store = Store()
    try:
        ist = now or datetime.now(tz=IST)
        due = tickers_for_slot(tickers, store, kind=kind, now=ist)
        first = store.filing_count() == 0
        notify = notify_backfill or not first
        if due:
            if fixture:
                stats = poll_fixture(fixture, due, store, notify=notify)
            else:
                stats = poll_tickers(due, store, BSESource(), notify=notify)
            print(
                f"slot={kind} names={len(due)} "
                f"candidate={stats['candidate']} priority={stats['priority']} "
                f"kill={stats['kill']} low={stats['low']} "
                f"notified={stats['notified']} collapsed={stats['collapsed']} "
                f"extracted={stats['extracted']} scored={stats['scored']}"
            )
        packs = deliver_packs(tickers, store, notify=True, now=ist)
        nudged = deliver_weekly_nudge(tickers, store, notify=True, now=ist)
        if packs or nudged:
            print(f"slot={kind} packs={packs} weekly_nudge={int(nudged)}")
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
