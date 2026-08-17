from __future__ import annotations

import argparse
import sys
from datetime import date

from src.context import context_command
from src.ledger import LedgerError, Ticker, by_symbol, load_tickers
from src.pack import pack_command
from src.portfolio.base import Holding
from src.portfolio.reconcile import reconcile, thesis_less_holdings
from src.quotes import last_price, pct_return
from src.store import Store


def _fmt_qty(qty: float) -> str:
    if qty == int(qty):
        return str(int(qty))
    return f"{qty:.2f}"


def _fmt_price(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}"


def _fmt_ret(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}%"


def _fmt_s(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}"


def _table_order(tickers: list[Ticker]) -> list[Ticker]:
    outstanding = [t for t in tickers if t.status == "no_thesis"]
    rest = [t for t in tickers if t.status != "no_thesis"]
    return outstanding + rest


def render_table(
    *,
    fetch_quotes: bool = True,
    tickers: list[Ticker] | None = None,
    store: Store | None = None,
) -> str:
    own_store = store is None
    tickers = tickers if tickers is not None else load_tickers()
    store = store or Store()
    try:
        cached = store.holdings_cache()
        missing = len(thesis_less_holdings(tickers, cached)) + sum(
            1 for t in tickers if t.status == "no_thesis"
        )
        rows: list[tuple[str, ...]] = []
        headers = ("SYMBOL", "QTY", "AVG COST", "LAST", "RETURN", "S", "BAND", "THESIS", "NEXT")
        for ticker in _table_order(tickers):
            last = last_price(ticker) if fetch_quotes else None
            score_row = store.latest_score(ticker.symbol)
            s_val = None if score_row is None or score_row["S"] is None else float(score_row["S"])
            band = "—" if score_row is None or not score_row["band"] else str(score_row["band"])
            nxt = store.next_event(ticker.symbol) or (
                f"Results due {ticker.results_due.isoformat()}" if ticker.results_due else "—"
            )
            rows.append(
                (
                    ticker.symbol,
                    _fmt_qty(ticker.qty),
                    _fmt_price(ticker.avg_cost),
                    _fmt_price(last),
                    _fmt_ret(pct_return(last, ticker.avg_cost)),
                    _fmt_s(s_val),
                    band,
                    ticker.thesis_short(),
                    nxt,
                )
            )
    finally:
        if own_store:
            store.close()
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt(cols: tuple[str, ...]) -> str:
        return "  ".join(col.ljust(widths[i]) for i, col in enumerate(cols))

    lines = [
        f"thesis-less holdings: {missing}",
        "",
        fmt(headers),
        "  ".join("-" * w for w in widths),
    ]
    lines.extend(fmt(row) for row in rows)
    return "\n".join(lines)


def sync_holdings(
    holdings: list[Holding],
    tickers: list[Ticker],
    store: Store,
) -> list[str]:
    """Cache Groww holdings and return drift lines. Does not write the ledger."""
    store.replace_holdings_cache(holdings)
    return reconcile(tickers, holdings)


def sync_command(*, store: Store | None = None, portfolio=None) -> int:
    from src.portfolio.groww import GrowwError, GrowwPortfolio

    own_store = store is None
    store = store or Store()
    try:
        tickers = load_tickers()
        source = portfolio if portfolio is not None else GrowwPortfolio()
        holdings = source.fetch()
        lines = sync_holdings(holdings, tickers, store)
        for line in lines:
            print(line)
        return 0
    except GrowwError as exc:
        print(f"pos sync: {exc}", file=sys.stderr)
        return 1
    except LedgerError as exc:
        print(f"pos sync: {exc}", file=sys.stderr)
        return 1
    finally:
        if own_store:
            store.close()


def decide_command(
    symbol: str,
    action: str,
    note: str = "",
    *,
    anticipatory: bool = False,
    store: Store | None = None,
    tickers: list[Ticker] | None = None,
) -> int:
    own_store = store is None
    store = store or Store()
    try:
        book = tickers if tickers is not None else load_tickers()
        ticker = by_symbol(book, symbol)
        row_id = store.insert_decision(
            ticker=ticker.symbol,
            action=action,
            note=note,
            S_at_time=store.latest_S(ticker.symbol),
            anticipatory=anticipatory,
        )
        row = store.conn.execute(
            "SELECT * FROM decisions WHERE id = ?", (row_id,)
        ).fetchone()
        flag = " anticipatory" if row["anticipatory"] else ""
        print(f"{row['ticker']} {row['action']}{flag} {row['note']}".rstrip())
        return 0
    except LedgerError as exc:
        print(f"pos decide: {exc}", file=sys.stderr)
        return 1
    finally:
        if own_store:
            store.close()


def list_decisions_command(
    *,
    anticipatory: bool = False,
    store: Store | None = None,
) -> int:
    own_store = store is None
    store = store or Store()
    try:
        rows = store.decisions_for(anticipatory=True if anticipatory else None)
        for row in rows:
            flag = " anticipatory" if row["anticipatory"] else ""
            s_bit = f" S={row['S_at_time']}" if row["S_at_time"] is not None else ""
            print(
                f"{row['ticker']} {row['decided_at']} {row['action']}{flag}{s_bit} "
                f"{row['note']}".rstrip()
            )
        return 0
    finally:
        if own_store:
            store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pos",
        description="Holdings table: return vs cost, last S, thesis, next event",
    )
    parser.add_argument(
        "--no-quotes",
        action="store_true",
        help="skip delayed quotes (offline / tests)",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser(
        "sync",
        help="fetch Groww holdings and print ledger drift (read-only)",
    )
    ctx = sub.add_parser(
        "context",
        help="print local markdown for one name (no network)",
    )
    ctx.add_argument("symbol")
    ctx.add_argument("--filings", type=int, default=20, metavar="N")
    ctx.add_argument("--since", type=date.fromisoformat, default=None, metavar="YYYY-MM-DD")
    decide = sub.add_parser(
        "decide",
        help="stamp a user decision against a ledger name",
    )
    decide.add_argument("symbol")
    decide.add_argument("action")
    decide.add_argument("note", nargs="?", default="")
    decide.add_argument(
        "--anticipatory",
        action="store_true",
        help="decision made ahead of a results print",
    )
    listed = sub.add_parser("decisions", help="list stamped decisions")
    listed.add_argument(
        "--anticipatory",
        action="store_true",
        help="only decisions made ahead of a results print",
    )
    pack = sub.add_parser(
        "pack",
        help="print the earnings pack for names with results due soon",
    )
    pack.add_argument("symbol", nargs="?")
    pack.add_argument(
        "--notify",
        action="store_true",
        help="also send a macOS notification for eligible packs",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "sync":
            return sync_command()
        if args.command == "context":
            return context_command(
                args.symbol,
                filings_n=args.filings,
                since=args.since,
            )
        if args.command == "decide":
            return decide_command(
                args.symbol,
                args.action,
                args.note,
                anticipatory=args.anticipatory,
            )
        if args.command == "decisions":
            return list_decisions_command(anticipatory=args.anticipatory)
        if args.command == "pack":
            return pack_command(args.symbol, notify=args.notify)
        print(render_table(fetch_quotes=not args.no_quotes))
        return 0
    except LedgerError as exc:
        print(f"cli: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
