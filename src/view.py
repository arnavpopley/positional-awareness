from __future__ import annotations

from dataclasses import dataclass

from src.ledger import Ticker
from src.portfolio.reconcile import thesis_less_holdings
from src.quotes import pct_return
from src.store import Store


def fmt_qty(qty: float) -> str:
    if qty == int(qty):
        return str(int(qty))
    return f"{qty:.2f}"


def fmt_price(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}"


def fmt_ret(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}%"


def fmt_s(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}"


def table_order(tickers: list[Ticker]) -> list[Ticker]:
    outstanding = [t for t in tickers if t.status == "no_thesis"]
    rest = [t for t in tickers if t.status != "no_thesis"]
    return outstanding + rest


@dataclass(frozen=True)
class BookRow:
    symbol: str
    status: str
    qty: str
    avg_cost: str
    cmp: str
    ret: str
    ret_value: float | None
    S: str
    band: str
    thesis: str
    thesis_short: str
    next_event: str


def book_rows(
    tickers: list[Ticker],
    store: Store,
    *,
    fetch_quotes: bool = True,
    prices: dict[str, float] | None = None,
) -> tuple[int, list[BookRow]]:
    cached = store.holdings_cache()
    missing = len(thesis_less_holdings(tickers, cached)) + sum(
        1 for t in tickers if t.status == "no_thesis"
    )
    if prices is None:
        prices = _cmp_prices(tickers) if fetch_quotes else {}
    rows: list[BookRow] = []
    for ticker in table_order(tickers):
        last = prices.get(ticker.symbol)
        score_row = store.latest_score(ticker.symbol)
        s_val = None if score_row is None or score_row["S"] is None else float(score_row["S"])
        band = "—" if score_row is None or not score_row["band"] else str(score_row["band"])
        nxt = store.next_event(ticker.symbol) or (
            f"Results due {ticker.results_due.isoformat()}" if ticker.results_due else "—"
        )
        ret_val = pct_return(last, ticker.avg_cost)
        rows.append(
            BookRow(
                symbol=ticker.symbol,
                status=ticker.status,
                qty=fmt_qty(ticker.qty),
                avg_cost=fmt_price(ticker.avg_cost),
                cmp=fmt_price(last),
                ret=fmt_ret(ret_val),
                ret_value=ret_val,
                S=fmt_s(s_val),
                band=band,
                thesis=ticker.thesis,
                thesis_short=ticker.thesis_short(),
                next_event=nxt,
            )
        )
    return missing, rows


def _cmp_prices(tickers: list[Ticker]) -> dict[str, float]:
    from src.portfolio.groww import GrowwError, GrowwPortfolio

    try:
        return GrowwPortfolio().ltp_map(tickers)
    except GrowwError:
        return {}
