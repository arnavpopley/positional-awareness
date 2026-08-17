from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime

from src.ledger import LedgerError, Ticker, by_symbol, load_tickers
from src.notify import notify_message
from src.schedule import RESULTS_WEEK_DAYS, now_ist
from src.store import Store

NUDGE_STATUSES = frozenset({"event", "manual"})
PACK_STATUSES = frozenset({"held", "exiting"})
NUDGE_META_KEY = "nudge_week"
PRINT_COUNT = 4


@dataclass(frozen=True)
class Pack:
    symbol: str
    due: date
    title: str
    body: str
    text: str


def _due_date(ticker: Ticker, store: Store) -> date | None:
    stored = store.results_due(ticker.symbol)
    if stored:
        return stored
    return ticker.results_due


def _kpi_to_watch(ticker: Ticker) -> str | None:
    for condition in ticker.conditions:
        if condition.check != "quantitative":
            continue
        return condition.kpi or condition.text
    if ticker.kpis:
        return ticker.kpis[0].name
    return None


def _fmt_num(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


def _fmt_s(value: float | None) -> str:
    if value is None:
        return "undefined"
    return f"{value:+.2f}"


def _last_prints(ticker: Ticker, store: Store) -> str:
    rows = store.kpi_prints_for(ticker.symbol)
    watch = _kpi_to_watch(ticker)
    if watch:
        named = [row for row in rows if row["kpi_name"] == watch]
        if named:
            rows = named
    chosen = list(rows)[-PRINT_COUNT:]
    if not chosen:
        return "none"
    return "; ".join(
        f"{row['period']} {row['kpi_name']}={_fmt_num(float(row['value']))}"
        for row in chosen
    )


def _s_line(ticker: Ticker, store: Store) -> str:
    row = store.latest_score(ticker.symbol)
    if row is None:
        return "S=undefined"
    s_bit = f"S={_fmt_s(None if row['S'] is None else float(row['S']))}"
    if row["band"]:
        s_bit += f"  {row['band']}"
    if row["low_confidence"]:
        s_bit += "  low_confidence"
    return s_bit


def pack_due(ticker: Ticker, store: Store, now: datetime | None = None) -> date | None:
    """Results date if a pack should go out now. None if silent."""
    if ticker.status not in PACK_STATUSES:
        return None
    due = _due_date(ticker, store)
    if due is None:
        return None
    if store.results_filed_for(ticker.symbol) == due:
        return None
    ist = now_ist(now)
    days = (due - ist.date()).days
    if days < 0 or days > RESULTS_WEEK_DAYS:
        return None
    if store.pack_sent_for(ticker.symbol) == due:
        return None
    return due


def render_pack(ticker: Ticker, store: Store, *, due: date | None = None) -> Pack:
    due = due or _due_date(ticker, store)
    if due is None:
        raise LedgerError(f"{ticker.symbol}: no results date")
    watch = _kpi_to_watch(ticker) or "none"
    s_line = _s_line(ticker, store)
    prints = _last_prints(ticker, store)
    thesis = " ".join(ticker.thesis.split()) or "(none)"
    text = "\n".join(
        [
            f"{ticker.symbol} · results due {due.isoformat()}",
            "",
            thesis,
            "",
            f"KPI to watch: {watch}",
            f"Last prints: {prints}",
            s_line,
            f"confidence={ticker.confidence}",
        ]
    )
    body = (
        f"Results due {due.isoformat()}. KPI: {watch}. "
        f"{s_line}. confidence={ticker.confidence}"
    )
    return Pack(
        symbol=ticker.symbol,
        due=due,
        title=f"{ticker.symbol} · pack",
        body=body,
        text=text,
    )


def deliver_packs(
    tickers: list[Ticker],
    store: Store,
    *,
    notify: bool,
    now: datetime | None = None,
    notifier=None,
) -> int:
    """Print and optionally ping packs that are due. Once per results date."""
    send = notifier or notify_message
    sent = 0
    for ticker in tickers:
        due = pack_due(ticker, store, now)
        if due is None:
            continue
        pack = render_pack(ticker, store, due=due)
        print(pack.text)
        if notify:
            send(pack.title, pack.body)
            store.mark_pack_sent(ticker.symbol, due)
        sent += 1
    return sent


def iso_week_key(now: datetime | None = None) -> str:
    year, week, _ = now_ist(now).isocalendar()
    return f"{year}-W{week:02d}"


def weekly_nudge_body(tickers: list[Ticker]) -> str | None:
    parked = [t for t in tickers if t.status in NUDGE_STATUSES]
    if not parked:
        return None
    bits = [f"{t.symbol} {t.status}" for t in parked]
    return "event/manual this week: " + " · ".join(bits)


def deliver_weekly_nudge(
    tickers: list[Ticker],
    store: Store,
    *,
    notify: bool,
    now: datetime | None = None,
    notifier=None,
) -> bool:
    """One ping per ISO week for event and manual names. Silent if none."""
    body = weekly_nudge_body(tickers)
    if body is None:
        return False
    week = iso_week_key(now)
    if store.get_meta(NUDGE_META_KEY) == week:
        return False
    title = "weekly nudge"
    print(f"{title}: {body}")
    if notify:
        send = notifier or notify_message
        send(title, body)
        store.set_meta(NUDGE_META_KEY, week)
    return True


def pack_command(
    symbol: str | None = None,
    *,
    notify: bool = False,
    store: Store | None = None,
    tickers: list[Ticker] | None = None,
    now: datetime | None = None,
) -> int:
    own_store = store is None
    store = store or Store()
    try:
        book = tickers if tickers is not None else load_tickers()
        if symbol:
            ticker = by_symbol(book, symbol)
            pack = render_pack(ticker, store)
            print(pack.text)
            due = pack_due(ticker, store, now)
            if notify and due is not None:
                notify_message(pack.title, pack.body)
                store.mark_pack_sent(ticker.symbol, due)
            return 0
        sent = deliver_packs(book, store, notify=notify, now=now)
        if sent == 0:
            print("no packs due")
        return 0
    except LedgerError as exc:
        print(f"pos pack: {exc}", file=sys.stderr)
        return 1
    finally:
        if own_store:
            store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Earnings pack for names with results due soon")
    parser.add_argument("symbol", nargs="?")
    parser.add_argument(
        "--notify",
        action="store_true",
        help="also send a macOS notification for eligible packs",
    )
    args = parser.parse_args(argv)
    return pack_command(args.symbol, notify=args.notify)


if __name__ == "__main__":
    raise SystemExit(main())
