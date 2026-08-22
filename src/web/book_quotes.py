from __future__ import annotations

from src.ledger import Ticker
from src.portfolio.base import Holding
from src.portfolio.groww import GrowwError, GrowwPortfolio
from src.quotes import last_price, pct_return
from src.view import fmt_price, fmt_qty, fmt_ret


def _holding_for(ticker: Ticker, holdings: list[Holding]) -> Holding | None:
    nse = (ticker.nse_symbol or "").strip().upper()
    for holding in holdings:
        if nse and holding.symbol == nse:
            return holding
        if holding.symbol == ticker.symbol:
            return holding
    return None


def book_quotes(tickers: list[Ticker]) -> dict[str, dict]:
    """Groww qty/cost + CMP. Delayed LTP, not a websocket. Never places a trade."""
    port = GrowwPortfolio()
    holdings: list[Holding] = []
    try:
        holdings = port.fetch()
    except GrowwError:
        holdings = []
    try:
        prices = port.ltp_map(tickers)
    except GrowwError:
        prices = {}
    out: dict[str, dict] = {}
    for ticker in tickers:
        held = _holding_for(ticker, holdings)
        qty = held.qty if held is not None else ticker.qty
        cost = held.avg_cost if held is not None else ticker.avg_cost
        last = prices.get(ticker.symbol)
        if last is None:
            last = last_price(ticker, timeout=4)
        ret = pct_return(last, cost)
        out[ticker.symbol] = {
            "qty": fmt_qty(qty),
            "cost": fmt_price(cost),
            "cmp": fmt_price(last),
            "ret": fmt_ret(ret),
            "up": ret is not None and ret > 0,
            "down": ret is not None and ret < 0,
        }
    return out
