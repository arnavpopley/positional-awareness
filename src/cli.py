from __future__ import annotations

import argparse
import sys

from src.ledger import LedgerError, Ticker, load_tickers
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
        missing = len(thesis_less_holdings(tickers, cached))
        rows: list[tuple[str, ...]] = []
        headers = ("SYMBOL", "QTY", "AVG COST", "LAST", "RETURN", "THESIS", "NEXT")
        for ticker in tickers:
            last = last_price(ticker) if fetch_quotes else None
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pos",
        description="Holdings table: return vs cost, thesis, next event",
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
    args = parser.parse_args(argv)
    try:
        if args.command == "sync":
            return sync_command()
        print(render_table(fetch_quotes=not args.no_quotes))
        return 0
    except LedgerError as exc:
        print(f"cli: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
