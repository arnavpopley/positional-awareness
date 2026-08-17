from __future__ import annotations

from src.ledger import Ticker
from src.store import Store
from src.view import book_rows, fmt_price, fmt_qty, fmt_s

FACTORS = ("kpi", "book", "industry", "price", "guidance")


def group_prints(rows) -> list[tuple[str, list]]:
    order: list[str] = []
    buckets: dict[str, list] = {}
    for row in rows:
        name = str(row["kpi_name"])
        if name not in buckets:
            order.append(name)
            buckets[name] = []
        buckets[name].append(row)
    return [(name, buckets[name]) for name in order]


def factor_lines(score_row) -> list[tuple[str, str]]:
    if score_row is None:
        return [(name, "n/a") for name in FACTORS]
    lines: list[tuple[str, str]] = []
    for name in FACTORS:
        raw = score_row[f"x_{name}"]
        if raw is None:
            lines.append((name, "n/a"))
        else:
            lines.append((name, f"{float(raw):+.2f}"))
    return lines


def flags(*, hosted: bool = False, pulse: bool = True, defer_quotes: bool = False) -> dict:
    return {"hosted": hosted, "pulse": pulse, "defer_quotes": defer_quotes}


def index_context(
    tickers: list[Ticker],
    store: Store,
    *,
    fetch_quotes: bool = False,
    hosted: bool = False,
    pulse: bool = True,
    defer_quotes: bool = False,
) -> dict:
    missing, rows = book_rows(tickers, store, fetch_quotes=fetch_quotes)
    ctx = flags(hosted=hosted, pulse=pulse, defer_quotes=defer_quotes)
    ctx.update({"missing": missing, "rows": rows})
    return ctx


def name_context(
    ticker: Ticker,
    store: Store,
    *,
    hosted: bool = False,
    pulse: bool = True,
) -> dict:
    score_row = store.latest_score(ticker.symbol)
    s_val = None if score_row is None or score_row["S"] is None else float(score_row["S"])
    band = "" if score_row is None or not score_row["band"] else str(score_row["band"])
    ctx = flags(hosted=hosted, pulse=pulse, defer_quotes=False)
    ctx.update(
        {
            "ticker": ticker,
            "qty": fmt_qty(ticker.qty),
            "avg_cost": fmt_price(ticker.avg_cost),
            "S": fmt_s(s_val),
            "band": band,
            "low_confidence": bool(score_row["low_confidence"]) if score_row else False,
            "factors": factor_lines(score_row),
            "next_event": store.next_event(ticker.symbol)
            or (
                f"Results due {ticker.results_due.isoformat()}"
                if ticker.results_due
                else None
            ),
            "quantitative": [c for c in ticker.conditions if c.check == "quantitative"],
            "manual": [c for c in ticker.conditions if c.check == "manual"],
            "touched": store.current_touches(ticker.symbol),
            "filings": store.filings_for(ticker.symbol, limit=20),
            "prints": group_prints(store.kpi_prints_for(ticker.symbol)),
            "decisions": store.decisions_for(ticker.symbol),
        }
    )
    return ctx
