from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests
import yaml

from src.cli import render_table, sync_command, sync_holdings
from src.ledger import Ticker, parse_ticker
from src.main import poll_fixture
from src.portfolio.base import Holding
from src.portfolio.groww import GrowwError, GrowwPortfolio
from src.portfolio.reconcile import reconcile
from src.portfolio.yaml_portfolio import YamlPortfolio
from src.store import Store

FIXTURE = Path("tests/fixtures/groww_holdings.json")
SECRET = "groww-test-token-do-not-leak-9f3a"


def _ticker(
    symbol: str,
    *,
    status: str = "held",
    qty: float = 100,
    avg_cost: float = 45.5,
    thesis: str = "Why this position exists.",
) -> Ticker:
    return parse_ticker(
        {
            "symbol": symbol,
            "bse_code": "1",
            "status": status,
            "qty": qty,
            "avg_cost": avg_cost,
            "thesis": thesis,
            "kpis": [{"name": "rev"}],
        }
    )


def _holding(symbol: str, *, qty: float = 100, avg_cost: float = 45.5, isin: str = "") -> Holding:
    return Holding(symbol=symbol, isin=isin, qty=qty, avg_cost=avg_cost)


def test_yaml_portfolio_reads_example_without_groww_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GROWW_ACCESS_TOKEN", raising=False)
    holdings = YamlPortfolio(Path("config/tickers.example.yaml")).fetch()
    assert holdings[0].symbol == "SUZLON"
    assert holdings[0].qty == 0


def test_reconcile_match_is_silent():
    lines = reconcile([_ticker("SUZLON")], [_holding("SUZLON")])
    assert lines == []


def test_reconcile_holding_with_no_thesis():
    lines = reconcile([_ticker("SUZLON")], [_holding("SUZLON"), _holding("RELIANCE", qty=10)])
    assert lines == ["HOLDING WITH NO THESIS: RELIANCE qty=10"]


def test_reconcile_ledger_entry_not_held():
    lines = reconcile([_ticker("SUZLON"), _ticker("INFY", qty=5, avg_cost=10)], [_holding("SUZLON")])
    assert lines == ["LEDGER ENTRY NOT HELD: INFY"]


def test_reconcile_watchlist_without_groww_holding_is_not_reported():
    lines = reconcile(
        [_ticker("SUZLON"), _ticker("INFY", status="watchlist", qty=0, avg_cost=0)],
        [_holding("SUZLON")],
    )
    assert lines == []


def test_reconcile_qty_drift():
    lines = reconcile([_ticker("SUZLON", qty=80, avg_cost=45.5)], [_holding("SUZLON", qty=100)])
    assert lines == [
        "DRIFT: SUZLON ledger qty=80 cost=45.50 / groww qty=100 cost=45.50"
    ]


def test_groww_fetch_parses_fixture_and_does_not_hit_network():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    session = MagicMock()
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    session.get.return_value = response

    holdings = GrowwPortfolio(token=SECRET, session=session).fetch()
    assert holdings == [
        Holding(symbol="SUZLON", isin="INE040H01021", qty=100.0, avg_cost=45.5)
    ]
    url = session.get.call_args.args[0]
    assert url == "https://api.groww.in/v1/holdings/user"
    assert "positions" not in url
    headers = session.get.call_args.kwargs.get("headers") or {}
    assert "Authorization" not in headers
    assert SECRET not in repr(session.get.call_args)


def test_token_never_appears_in_stdout_or_exception(capsys: pytest.CaptureFixture[str]):
    session = MagicMock()
    session.get.side_effect = requests.HTTPError(
        f"401 Client Error token={SECRET} for url=https://api.groww.in/v1/holdings/user"
    )
    with pytest.raises(GrowwError) as caught:
        GrowwPortfolio(token=SECRET, session=session).fetch()
    assert SECRET not in str(caught.value)
    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err


def test_sync_caches_and_cli_table_shows_thesis_less_count(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    tickers = [_ticker("SUZLON")]
    lines = sync_holdings(
        [_holding("SUZLON"), _holding("RELIANCE", qty=3)],
        tickers,
        store,
    )
    assert "HOLDING WITH NO THESIS: RELIANCE qty=3" in lines
    table = render_table(fetch_quotes=False, tickers=tickers, store=store)
    assert table.startswith("thesis-less holdings: 1")
    cached = store.holdings_cache()
    assert {h.symbol for h in cached} == {"RELIANCE", "SUZLON"}
    store.close()


def test_sync_never_writes_the_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ledger = tmp_path / "tickers.yaml"
    original = yaml.dump(
        [
            {
                "symbol": "SUZLON",
                "bse_code": "532667",
                "status": "held",
                "qty": 10,
                "avg_cost": 40,
                "thesis": "Why this position exists.",
                "kpis": [{"name": "rev"}],
            }
        ]
    )
    ledger.write_text(original, encoding="utf-8")
    monkeypatch.setattr("src.cli.load_tickers", lambda: [_ticker("SUZLON", qty=10, avg_cost=40)])
    store = Store(tmp_path / "pa.sqlite")

    class Fake:
        def fetch(self):
            return [_holding("SUZLON", qty=99, avg_cost=1)]

    code = sync_command(store=store, portfolio=Fake())
    assert code == 0
    assert ledger.read_text(encoding="utf-8") == original
    store.close()


def test_poller_makes_no_http_call_to_groww(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    hits: list[str] = []

    def blocked(self, method, url, *args, **kwargs):
        hits.append(str(url))
        if "groww.in" in str(url).lower():
            raise AssertionError(f"poller called groww: {url}")
        raise RuntimeError("no network in this test")

    monkeypatch.setattr(requests.Session, "request", blocked)
    store = Store(tmp_path / "pa.sqlite")
    from src.ledger import load_tickers

    tickers = load_tickers(Path("config/tickers.example.yaml"))
    poll_fixture(
        Path("tests/fixtures/anngetdata.json"),
        tickers,
        store,
        notify=False,
    )
    assert not any("groww.in" in url.lower() for url in hits)
    store.close()


def test_poller_modules_do_not_import_groww():
    for path in (Path("src/main.py"), Path("src/schedule.py")):
        text = path.read_text(encoding="utf-8")
        assert "groww.in" not in text.lower()
        assert "GrowwPortfolio" not in text
        assert "GROWW" not in text
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "portfolio.groww" not in node.module
                assert node.module != "src.portfolio.groww"


def test_importing_poller_does_not_load_groww_module():
    import importlib
    import sys

    sys.modules.pop("src.portfolio.groww", None)
    import src.main as main

    importlib.reload(main)
    assert "src.portfolio.groww" not in sys.modules


def test_no_growwapi_import_in_src():
    for path in Path("src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "growwapi"
                    assert not alias.name.startswith("growwapi.")
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module != "growwapi"
                assert not node.module.startswith("growwapi.")
