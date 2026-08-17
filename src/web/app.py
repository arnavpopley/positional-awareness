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
from src.portfolio.groww import GrowwError, GrowwPortfolio
from src.quotes import pct_return
from src.store import Store
from src.view import fmt_price, fmt_ret
from src.web.render import index_context, name_context

HERE = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(HERE / "templates"))


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
            ctx = index_context(
                _book(),
                store,
                fetch_quotes=False,
                hosted=False,
                pulse=True,
                defer_quotes=defer_quotes,
            )
        except LedgerError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            store.close()
        return TEMPLATES.TemplateResponse(request, "index.html", ctx)

    @app.get("/api/quotes")
    def api_quotes() -> dict[str, dict]:
        book = _book()
        try:
            prices = GrowwPortfolio().ltp_map(book)
        except GrowwError:
            prices = {}
        out: dict[str, dict] = {}
        for ticker in book:
            last = prices.get(ticker.symbol)
            ret = pct_return(last, ticker.avg_cost)
            out[ticker.symbol] = {
                "cmp": fmt_price(last),
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
            ctx = name_context(ticker, store, hosted=False, pulse=True)
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
        help="skip Groww CMP",
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
