from __future__ import annotations

import sys

import requests

from src.ledger import Ticker, by_symbol, load_tickers
from src.sources.bse import HEADERS, HOME_URL, TIMEOUT

QUOTE_URL = "https://api.bseindia.com/BseIndiaAPI/api/getScripHeaderData/w"


def last_price(
    ticker: Ticker,
    session: requests.Session | None = None,
    *,
    timeout: float | None = None,
) -> float | None:
    """Delayed public quote (BSE header). Not a live ticker. Not vs Nifty."""
    if not ticker.bse_code:
        return None
    wait = TIMEOUT if timeout is None else timeout
    sess = session or requests.Session()
    sess.headers.update(HEADERS)
    try:
        sess.get(HOME_URL, timeout=wait)
        response = sess.get(
            QUOTE_URL,
            params={"Debtflag": "", "scripcode": ticker.bse_code, "seriesid": ""},
            timeout=wait,
        )
        response.raise_for_status()
        payload = response.json()
        ltp = (payload.get("CurrRate") or {}).get("LTP")
        if ltp is None or ltp == "":
            return None
        return float(str(ltp).replace(",", ""))
    except (requests.RequestException, TypeError, ValueError, AttributeError):
        return None


def pct_return(last: float | None, avg_cost: float) -> float | None:
    if last is None or avg_cost <= 0:
        return None
    return (last - avg_cost) / avg_cost * 100


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m src.quotes SYMBOL", file=sys.stderr)
        return 2
    ticker = by_symbol(load_tickers(), args[0])
    price = last_price(ticker)
    if price is None:
        print(f"{ticker.symbol}\tunavailable")
        return 1
    print(f"{ticker.symbol}\t{price}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
