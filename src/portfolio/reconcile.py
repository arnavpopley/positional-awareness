from __future__ import annotations

from src.ledger import Ticker
from src.portfolio.base import Holding


def _qty(value: float) -> str:
    if float(value) == int(value):
        return str(int(value))
    return f"{value:g}"


def _cost(value: float) -> str:
    return f"{value:.2f}"


def _index(tickers: list[Ticker]) -> dict[str, Ticker]:
    by_symbol: dict[str, Ticker] = {}
    for ticker in tickers:
        by_symbol[ticker.symbol] = ticker
        if ticker.nse_symbol:
            by_symbol.setdefault(ticker.nse_symbol, ticker)
        if ticker.isin:
            by_symbol.setdefault(ticker.isin, ticker)
    return by_symbol


def _match(holding: Holding, index: dict[str, Ticker]) -> Ticker | None:
    if holding.symbol in index:
        return index[holding.symbol]
    if holding.isin and holding.isin in index:
        return index[holding.isin]
    return None


def thesis_less_holdings(tickers: list[Ticker], holdings: list[Holding]) -> list[Holding]:
    index = _index(tickers)
    return [h for h in holdings if _match(h, index) is None]


def reconcile(tickers: list[Ticker], holdings: list[Holding]) -> list[str]:
    """Report drift only. Never create, update, or delete ledger rows."""
    index = _index(tickers)
    matched_tickers: set[str] = set()
    lines: list[str] = []

    for holding in sorted(holdings, key=lambda h: h.symbol):
        ticker = _match(holding, index)
        if ticker is None:
            lines.append(
                f"HOLDING WITH NO THESIS: {holding.symbol} qty={_qty(holding.qty)}"
            )
            continue
        matched_tickers.add(ticker.symbol)
        if ticker.qty != holding.qty or ticker.avg_cost != holding.avg_cost:
            lines.append(
                f"DRIFT: {ticker.symbol} ledger qty={_qty(ticker.qty)} "
                f"cost={_cost(ticker.avg_cost)} / groww qty={_qty(holding.qty)} "
                f"cost={_cost(holding.avg_cost)}"
            )

    ledger_no_thesis = [
        f"NO_THESIS: {t.symbol}"
        for t in sorted(
            (t for t in tickers if t.status == "no_thesis"),
            key=lambda t: t.symbol,
        )
    ]
    held_unmatched = [
        t
        for t in tickers
        if t.status == "held" and t.symbol not in matched_tickers
    ]
    missing_lines = [
        f"LEDGER ENTRY NOT HELD: {t.symbol}"
        for t in sorted(held_unmatched, key=lambda t: t.symbol)
    ]
    # Specified order: groww unmatched, ledger no_thesis, not-held, then drift.
    groww_unmatched = [line for line in lines if line.startswith("HOLDING WITH NO THESIS:")]
    drift = [line for line in lines if line.startswith("DRIFT:")]
    return groww_unmatched + ledger_no_thesis + missing_lines + drift


def main(argv: list[str] | None = None) -> int:
    del argv
    print("reconcile(tickers, holdings) -> drift lines; never writes the ledger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

