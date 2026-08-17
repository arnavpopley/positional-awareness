from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.ledger import LedgerError, Ticker, by_symbol, load_tickers
from src.paths import TICKERS_PATH
from src.quotes import last_price, pct_return
from src.store import Store
from src.view import book_rows, fmt_price, fmt_qty, fmt_ret, fmt_s

HERE = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(HERE / "templates"))
FACTORS = ("kpi", "book", "industry", "price", "guidance")


def _group_prints(rows) -> list[tuple[str, list]]:
    order: list[str] = []
    buckets: dict[str, list] = {}
    for row in rows:
        name = str(row["kpi_name"])
        if name not in buckets:
            order.append(name)
            buckets[name] = []
        buckets[name].append(row)
    return [(name, buckets[name]) for name in order]


def _factor_lines(score_row) -> list[tuple[str, str]]:
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


def create_app(
    *,
    tickers: list[Ticker] | None = None,
    store_factory: Callable[[], Store] | None = None,
    defer_quotes: bool = True,
) -> FastAPI:
    """Read-only local page. Binds to localhost from `main`; never places a trade."""
    app = FastAPI(title="Positional Awareness", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    def _book() -> list[Ticker]:
        return tickers if tickers is not None else load_tickers()

    def _store() -> Store:
        return store_factory() if store_factory is not None else Store()

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        store = _store()
        try:
            missing, rows = book_rows(_book(), store, fetch_quotes=False)
        except LedgerError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            store.close()
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"missing": missing, "rows": rows, "defer_quotes": defer_quotes},
        )

    @app.get("/api/quotes")
    def api_quotes() -> dict[str, dict]:
        import requests as req

        sess = req.Session()
        out: dict[str, dict] = {}
        for ticker in _book():
            last = last_price(ticker, sess, timeout=4)
            ret = pct_return(last, ticker.avg_cost)
            out[ticker.symbol] = {
                "last": fmt_price(last),
                "ret": fmt_ret(ret),
                "up": ret is not None and ret > 0,
                "down": ret is not None and ret < 0,
            }
        return out

    @app.get("/api/pulse")
    def api_pulse() -> dict[str, int]:
        store = _store()
        try:
            yaml_mtime = 0
            if TICKERS_PATH.exists():
                yaml_mtime = TICKERS_PATH.stat().st_mtime_ns
            return {
                "filings": store.filing_count(),
                "scores": store.score_count(),
                "yaml": yaml_mtime,
            }
        finally:
            store.close()

    @app.get("/t/{symbol}", response_class=HTMLResponse)
    def name_page(request: Request, symbol: str) -> HTMLResponse:
        store = _store()
        try:
            ticker = by_symbol(_book(), symbol)
            score_row = store.latest_score(ticker.symbol)
            s_val = None if score_row is None or score_row["S"] is None else float(score_row["S"])
            band = "" if score_row is None or not score_row["band"] else str(score_row["band"])
            ctx = {
                "ticker": ticker,
                "qty": fmt_qty(ticker.qty),
                "avg_cost": fmt_price(ticker.avg_cost),
                "S": fmt_s(s_val),
                "band": band,
                "low_confidence": bool(score_row["low_confidence"]) if score_row else False,
                "factors": _factor_lines(score_row),
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
                "prints": _group_prints(store.kpi_prints_for(ticker.symbol)),
                "decisions": store.decisions_for(ticker.symbol),
            }
        except LedgerError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            store.close()
        return TEMPLATES.TemplateResponse(request, "name.html", ctx)

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only local page for the ledger (127.0.0.1)"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--no-quotes",
        action="store_true",
        help="skip delayed quotes",
    )
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        print("web: host must be localhost (this page is not a public site)", flush=True)
        return 2
    try:
        load_tickers()
    except LedgerError as exc:
        print(f"web: {exc}", flush=True)
        return 1
    import uvicorn

    uvicorn.run(
        create_app(defer_quotes=not args.no_quotes),
        host=args.host,
        port=args.port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
