from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.ledger import Kpi, Ticker
from src.schedule import tickers_for_slot
from src.store import Store

IST = ZoneInfo("Asia/Kolkata")


def _ticker(results_due=None) -> Ticker:
    return Ticker(
        symbol="SUZLON",
        bse_code="532667",
        nse_symbol="SUZLON",
        status="held",
        sector="wind",
        qty=0,
        avg_cost=0,
        confidence=70,
        review_by=None,
        thesis="Two sentences.",
        kpis=(Kpi(name="deliveries_mw", label="Deliveries", check="PPT"),),
        results_due=results_due,
    )


def test_ordinary_slot_skips_inside_15_min(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    t = _ticker()
    now = datetime(2026, 8, 14, 9, 30, tzinfo=IST)
    store.touch_fetch("SUZLON", now)
    assert tickers_for_slot([t], store, kind="ordinary", now=now) == []
    later = datetime(2026, 8, 14, 9, 46, tzinfo=IST)
    assert [x.symbol for x in tickers_for_slot([t], store, kind="ordinary", now=later)] == ["SUZLON"]
    store.close()


def test_interval_only_results_week_and_not_overnight(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    due = datetime(2026, 8, 17, tzinfo=IST).date()
    t = _ticker(results_due=due)
    overnight = datetime(2026, 8, 14, 22, 0, tzinfo=IST)
    assert tickers_for_slot([t], store, kind="interval", now=overnight) == []
    afternoon = datetime(2026, 8, 14, 12, 40, tzinfo=IST)
    names = [x.symbol for x in tickers_for_slot([t], store, kind="interval", now=afternoon)]
    assert names == ["SUZLON"]
    weekend = datetime(2026, 8, 15, 12, 0, tzinfo=IST)  # Saturday
    assert tickers_for_slot([t], store, kind="interval", now=weekend) == []
    store.close()


def test_ordinary_slot_skips_non_poll_statuses(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    now = datetime(2026, 8, 14, 9, 46, tzinfo=IST)
    held = _ticker()
    parked = Ticker(
        symbol="GOLDBEES",
        bse_code="",
        nse_symbol="GOLDBEES",
        status="manual",
        sector=None,
        qty=1,
        avg_cost=1,
        confidence=0,
        review_by=None,
        thesis="",
        kpis=(),
    )
    names = [
        x.symbol
        for x in tickers_for_slot([held, parked], store, kind="ordinary", now=now)
    ]
    assert names == ["SUZLON"]
    store.close()
