from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.ledger import parse_ticker
from src.store import Store
from src.web.app import create_app, main
from tests.helpers import filing


def _held():
    return parse_ticker(
        {
            "symbol": "SUZLON",
            "bse_code": "532667",
            "thesis": (
                "Two sentences. Why this position exists. "
                "A third sentence so the page must not truncate with an ellipsis."
            ),
            "confidence": 70,
            "conditions": [
                {
                    "text": "Order inflow stops growing",
                    "check": "quantitative",
                    "kpi": "order_inflow_ttm",
                    "threshold": "YoY decline for 2 consecutive quarters",
                    "severity": "material",
                }
            ],
        }
    )


def _client(tmp_path: Path) -> TestClient:
    db = tmp_path / "pa.sqlite"
    ticker = _held()
    store = Store(db)
    store.insert_filing(
        filing(
            headline="Financial Results",
            category="Result",
            subcategory="Financial Results",
            ann_id="web-1",
        ),
        "candidate",
    )
    store.close()
    app = create_app(
        tickers=[ticker],
        store_factory=lambda: Store(db),
    )
    return TestClient(app)


def test_book_page_lists_names(tmp_path: Path):
    client = _client(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert "SUZLON" in body
    assert "Two sentences" in body
    assert "must not truncate with an ellipsis" in body
    assert "…" not in body
    assert "never places a trade" in body
    for verb in ("buy", "sell", "add", "trim"):
        assert f">{verb}<" not in body.lower()


def test_name_page_shows_thesis_and_conditions(tmp_path: Path):
    client = _client(tmp_path)
    response = client.get("/t/SUZLON")
    assert response.status_code == 200
    body = response.text
    assert "Why this position exists." in body
    assert "Order inflow stops growing" in body
    assert "Financial Results" in body


def test_book_page_does_not_block_on_quotes(tmp_path: Path, monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("book page must not fetch quotes")

    monkeypatch.setattr("src.view.last_price", blocked)
    monkeypatch.setattr("src.quotes.last_price", blocked)
    client = _client(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "SUZLON" in response.text


def test_unknown_name_is_404(tmp_path: Path):
    client = _client(tmp_path)
    assert client.get("/t/NOSUCH").status_code == 404


def test_pulse_tracks_filings(tmp_path: Path):
    client = _client(tmp_path)
    first = client.get("/api/pulse")
    assert first.status_code == 200
    assert first.json()["filings"] == 1
    body = client.get("/").text
    assert "/static/pulse.js" in body


def test_web_refuses_non_localhost():
    assert main(["--host", "0.0.0.0"]) == 2
