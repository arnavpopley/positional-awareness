from __future__ import annotations

import argparse
import sys

from src.ledger import LedgerError, load_tickers
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


def render_table(*, fetch_quotes: bool = True) -> str:
    tickers = load_tickers()
    store = Store()
    try:
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
        store.close()
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    def fmt(cols: tuple[str, ...]) -> str:
        return "  ".join(col.ljust(widths[i]) for i, col in enumerate(cols))
    lines = [fmt(headers), "  ".join("-" * w for w in widths)]
    lines.extend(fmt(row) for row in rows)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Holdings table: return vs cost, thesis, next event")
    parser.add_argument(
        "--no-quotes",
        action="store_true",
        help="skip delayed quotes (offline / tests)",
    )
    args = parser.parse_args(argv)
    try:
        print(render_table(fetch_quotes=not args.no_quotes))
        return 0
    except LedgerError as exc:
        print(f"cli: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
