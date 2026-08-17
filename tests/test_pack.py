from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.cli import main, render_table
from src.ledger import parse_ticker
from src.main import run_slot
from src.pack import (
    deliver_packs,
    deliver_weekly_nudge,
    pack_due,
    render_pack,
)
from src.score import active, persist, score
from src.store import Store
from tests.helpers import filing

IST = ZoneInfo("Asia/Kolkata")


def _held(**extra):
    row = {
        "symbol": "SUZLON",
        "bse_code": "532667",
        "thesis": "Two sentences. Why this position exists.",
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
    row.update(extra)
    return parse_ticker(row)


def _event():
    return parse_ticker(
        {
            "symbol": "RELIANCE",
            "bse_code": "",
            "status": "event",
            "thesis": "Jio IPO is the event.",
        }
    )


def test_pack_when_due_in_three_days(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    ticker = _held()
    due = date(2026, 8, 20)
    store.set_results_due("SUZLON", due)
    now = datetime(2026, 8, 17, 12, 0, tzinfo=IST)
    assert pack_due(ticker, store, now) == due
    store.close()


def test_no_pack_when_due_in_twenty_days(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    ticker = _held()
    store.set_results_due("SUZLON", date(2026, 9, 6))
    now = datetime(2026, 8, 17, 12, 0, tzinfo=IST)
    assert pack_due(ticker, store, now) is None
    store.close()


def test_pack_once_per_due_date(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    ticker = _held()
    due = date(2026, 8, 20)
    store.set_results_due("SUZLON", due)
    now = datetime(2026, 8, 17, 12, 0, tzinfo=IST)
    pinged: list[str] = []

    def capture(title: str, body: str) -> bool:
        pinged.append(title)
        return True

    assert deliver_packs([ticker], store, notify=True, now=now, notifier=capture) == 1
    assert deliver_packs([ticker], store, notify=True, now=now, notifier=capture) == 0
    assert pinged == ["SUZLON · pack"]
    assert store.pack_sent_for("SUZLON") == due
    store.close()


def test_no_pack_after_results_filed(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    ticker = _held()
    due = date(2026, 8, 20)
    store.set_results_due("SUZLON", due)
    store.mark_results_filed("SUZLON", due)
    now = datetime(2026, 8, 17, 12, 0, tzinfo=IST)
    assert pack_due(ticker, store, now) is None
    store.close()


def test_pack_text_has_thesis_kpi_prints_and_s(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    ticker = _held()
    due = date(2026, 8, 20)
    store.set_results_due("SUZLON", due)
    fid = store.insert_filing(
        filing(
            headline="Financial Results",
            category="Result",
            subcategory="Financial Results",
            ann_id="pack-1",
        ),
        "candidate",
    )
    store.insert_kpi_print(
        ticker="SUZLON",
        kpi_name="order_inflow_ttm",
        period="Q1FY27",
        value=120.0,
        source_filing_id=fid,
    )
    persist(score(book=active(0.5), price=active(0.2)), store, filing_id=fid)
    pack = render_pack(ticker, store, due=due)
    assert "Two sentences. Why this position exists." in pack.text
    assert "KPI to watch: order_inflow_ttm" in pack.text
    assert "Q1FY27 order_inflow_ttm=120" in pack.text
    assert "S=" in pack.text
    assert "confidence=70" in pack.text
    assert "beat" not in pack.text.lower()
    for verb in ("add", "trim", "buy", "sell", "hold"):
        assert verb not in pack.text.lower().split()
    store.close()


def test_weekly_nudge_once_per_week(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    names = [_held(), _event()]
    now = datetime(2026, 8, 17, 8, 0, tzinfo=IST)
    pinged: list[str] = []

    def capture(title: str, body: str) -> bool:
        pinged.append(f"{title}: {body}")
        return True

    assert deliver_weekly_nudge(names, store, notify=True, now=now, notifier=capture)
    assert not deliver_weekly_nudge(names, store, notify=True, now=now, notifier=capture)
    assert len(pinged) == 1
    assert "RELIANCE event" in pinged[0]
    assert "SUZLON" not in pinged[0]
    store.close()


def test_run_slot_packs_when_no_names_to_poll(
    tmp_path: Path, monkeypatch
):
    store = Store(tmp_path / "pa.sqlite")
    ticker = _held()
    due = date(2026, 8, 20)
    store.set_results_due("SUZLON", due)
    now = datetime(2026, 8, 17, 12, 0, tzinfo=IST)
    store.touch_fetch("SUZLON", now)
    pinged: list[str] = []
    monkeypatch.setattr("src.main.load_tickers", lambda: [ticker])
    monkeypatch.setattr("src.main.Store", lambda: store)
    monkeypatch.setattr(
        "src.pack.notify_message",
        lambda title, body: pinged.append(title) or True,
    )
    run_slot("ordinary", now=now)
    again = Store(tmp_path / "pa.sqlite")
    assert again.pack_sent_for("SUZLON") == due
    assert "SUZLON · pack" in pinged
    again.close()


def test_pos_pack_prints_without_marking(
    tmp_path: Path, monkeypatch, capsys
):
    store = Store(tmp_path / "pa.sqlite")
    ticker = _held()
    due = date(2026, 8, 20)
    store.set_results_due("SUZLON", due)
    monkeypatch.setattr("src.pack.load_tickers", lambda: [ticker])
    monkeypatch.setattr("src.pack.Store", lambda: store)
    assert main(["pack", "SUZLON"]) == 0
    out = capsys.readouterr().out
    assert "results due 2026-08-20" in out
    closed = Store(tmp_path / "pa.sqlite")
    assert closed.pack_sent_for("SUZLON") is None
    closed.close()


def test_cli_table_includes_last_s(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    ticker = _held()
    fid = store.insert_filing(
        filing(
            headline="Financial Results",
            category="Result",
            subcategory="Financial Results",
            ann_id="table-s",
        ),
        "candidate",
    )
    persist(score(book=active(1.0), price=active(1.0)), store, filing_id=fid)
    table = render_table(fetch_quotes=False, tickers=[ticker], store=store)
    header = next(line for line in table.splitlines() if line.startswith("SYMBOL"))
    assert header.split()[:8] == [
        "SYMBOL",
        "QTY",
        "AVG",
        "COST",
        "CMP",
        "RETURN",
        "S",
        "BAND",
    ]
    assert "strongly positive" in table
    store.close()
