from __future__ import annotations

import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.ledger import LedgerError, Ticker, load_tickers
from src.portfolio.groww import GrowwError, GrowwPortfolio
from src.store import Store
from src.web.render import index_context, name_context

HERE = Path(__file__).resolve().parent
HOST = HERE / "host"
SITE_DIR = HERE.parent.parent / "site"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(HERE / "templates")),
        autoescape=select_autoescape(["html"]),
    )


def render_html(template: str, ctx: dict) -> str:
    return _env().get_template(template).render(**ctx)


def publish(
    dest: Path | None = None,
    *,
    tickers: list[Ticker] | None = None,
    store: Store | None = None,
    fetch_quotes: bool = True,
) -> Path:
    """Write a static snapshot. Holdings stay off git. Never places a trade."""
    own_store = store is None
    dest = dest or SITE_DIR
    tickers = tickers if tickers is not None else load_tickers()
    store = store or Store()
    try:
        prices: dict[str, float] = {}
        if fetch_quotes:
            try:
                prices = GrowwPortfolio().ltp_map(tickers)
            except GrowwError:
                prices = {}
        dest.mkdir(parents=True, exist_ok=True)
        static_dest = dest / "static"
        if static_dest.exists():
            shutil.rmtree(static_dest)
        shutil.copytree(HERE / "static", static_dest)
        shutil.copy(HERE / "host" / "login.html", dest / "login.html")
        index = render_html(
            "index.html",
            index_context(
                tickers,
                store,
                fetch_quotes=False,
                prices=prices,
                hosted=True,
                pulse=False,
                defer_quotes=True,
            ),
        )
        names: dict[str, str] = {"/": index}
        pages = dest / "t"
        if pages.exists():
            shutil.rmtree(pages)
        pages.mkdir()
        for ticker in tickers:
            html = render_html(
                "name.html",
                name_context(
                    ticker,
                    store,
                    hosted=True,
                    pulse=False,
                    prices=prices,
                    defer_quotes=True,
                ),
            )
            (pages / f"{ticker.symbol}.html").write_text(html, encoding="utf-8")
            names[f"/t/{ticker.symbol}"] = html
        (dest / "index.html").write_text(index, encoding="utf-8")
        (dest / "symbols.json").write_text(
            json.dumps(
                [
                    {
                        "symbol": ticker.symbol,
                        "nse_symbol": ticker.nse_symbol or ticker.symbol,
                    }
                    for ticker in tickers
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (dest / "bundle.json").write_text(
            json.dumps(names, ensure_ascii=False),
            encoding="utf-8",
        )
        return dest
    finally:
        if own_store:
            store.close()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Write a static snapshot for Vercel")
    parser.add_argument(
        "--no-quotes",
        action="store_true",
        help="skip Groww CMP (offline)",
    )
    args = parser.parse_args(argv)
    try:
        dest = publish(fetch_quotes=not args.no_quotes)
    except LedgerError as exc:
        print(f"publish: {exc}")
        return 1
    print(f"published {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
