from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests

from src.cli import main, render_table
from src.context import context_command, render_context
from src.ledger import parse_ticker
from src.store import Store
from tests.helpers import filing

IST = ZoneInfo("Asia/Kolkata")


def _held():
    return parse_ticker(
        {
            "symbol": "SUZLON",
            "bse_code": "532667",
            "thesis": "Two sentences. Why this position exists.",
            "conditions": [
                {
                    "text": "Order inflow stops growing",
                    "check": "quantitative",
                    "kpi": "order_inflow_ttm",
                    "threshold": "YoY decline for 2 consecutive quarters",
                    "severity": "material",
                },
                {
                    "text": "Moat erodes, story stops making sense",
                    "check": "manual",
                    "severity": "watch",
                },
            ],
        }
    )


def test_pos_context_makes_no_network_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    def blocked(self, method, url, *args, **kwargs):
        raise AssertionError(f"pos context must not call the network: {url}")

    monkeypatch.setattr(requests.Session, "request", blocked)
    store = Store(tmp_path / "pa.sqlite")
    ticker = _held()
    monkeypatch.setattr("src.context.load_tickers", lambda: [ticker])
    monkeypatch.setattr("src.context.Store", lambda: store)
    assert main(["context", "SUZLON", "--filings", "5"]) == 0
    out = capsys.readouterr().out
    assert "# SUZLON" in out
    assert "Two sentences. Why this position exists." in out
    assert "### Quantitative" in out
    assert "### Manual" in out
    store.close()


def test_context_includes_filings_kpis_and_decisions(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    ticker = _held()
    now = datetime(2026, 8, 16, 12, 0, tzinfo=IST)
    store.insert_filing(
        filing(
            headline="Financial Results for the quarter",
            category="Result",
            subcategory="Financial Results",
            filed_at=now,
            ann_id="ctx-1",
        ),
        "candidate",
    )
    store.insert_kpi_print(
        ticker="SUZLON",
        kpi_name="order_inflow_ttm",
        period="Q1FY27",
        value=120.0,
        source_filing_id=1,
    )
    store.insert_decision(
        ticker="SUZLON",
        action="pre_results",
        note="waiting on deliveries",
        anticipatory=True,
    )
    text = render_context(ticker, store, filings_n=20)
    assert "Financial Results" in text
    assert "Q1FY27: 120.0" in text
    assert "pre_results" in text
    assert "anticipatory" in text
    store.touch_condition(
        ticker="SUZLON",
        text="Order inflow stops growing",
        severity="material",
        check="quantitative",
        touched_at=now.date(),
    )
    text = render_context(ticker, store, filings_n=20)
    assert "## Currently touched" in text
    assert "Order inflow stops growing" in text
    assert "material" in text
    older = now - timedelta(days=10)
    store.insert_filing(
        filing(
            headline="Old print",
            category="Result",
            subcategory="Financial Results",
            filed_at=older,
            ann_id="ctx-old",
        ),
        "candidate",
    )
    bounded = render_context(ticker, store, filings_n=20, since=now.date())
    assert "Old print" not in bounded
    assert context_command("SUZLON", store=store, tickers=[ticker], filings_n=1) == 0
    store.close()


def test_cli_table_puts_no_thesis_first(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    held = _held()
    bare = parse_ticker({"symbol": "AAA", "bse_code": "2", "status": "no_thesis"})
    table = render_table(fetch_quotes=False, tickers=[held, bare], store=store)
    assert table.startswith("thesis-less holdings: 1")
    assert table.index("AAA") < table.index("SUZLON")
    store.close()
