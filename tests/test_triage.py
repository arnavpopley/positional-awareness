from datetime import date, timedelta
from pathlib import Path

from src.ledger import parse_ticker
from src.score import score_extraction
from src.store import Store
from src.triage import LEVEL_RECORD, LEVEL_REVIEW, WINDOW, escalate


def _held():
    return parse_ticker(
        {
            "symbol": "FOO",
            "bse_code": "1",
            "thesis": "why we own it",
            "conditions": [
                {
                    "text": "Order inflow stops growing",
                    "check": "quantitative",
                    "kpi": "order_inflow_ttm",
                    "severity": "material",
                },
                {
                    "text": "Working capital deteriorates",
                    "check": "quantitative",
                    "kpi": "working_capital_pct_sales",
                    "severity": "material",
                },
                {
                    "text": "Margin compresses as mix worsens",
                    "check": "quantitative",
                    "kpi": "ebitda_margin",
                    "severity": "material",
                },
                {
                    "text": "Promoter holding falls or pledge rises",
                    "check": "manual",
                    "severity": "structural",
                },
                {"text": "CFO departs", "check": "manual", "severity": "watch"},
            ],
        }
    )


def _touch(store: Store, ticker, text: str, *, when: date, severity: str | None = None):
    cond = next(c for c in ticker.conditions if c.text == text)
    store.touch_condition(
        ticker=ticker.symbol,
        text=cond.text,
        severity=severity or cond.severity,
        check=cond.check,
        touched_at=when,
    )


def test_single_material_produces_no_notification(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    ticker = _held()
    as_of = date(2026, 8, 17)
    _touch(store, ticker, "Order inflow stops growing", when=as_of)
    result = escalate(ticker, store, as_of=as_of)
    assert result.level == LEVEL_RECORD
    assert result.should_notify() is False
    store.close()


def test_two_material_within_two_quarters_escalates_to_review(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    ticker = _held()
    as_of = date(2026, 8, 17)
    _touch(store, ticker, "Order inflow stops growing", when=as_of)
    _touch(store, ticker, "Working capital deteriorates", when=as_of)
    result = escalate(ticker, store, as_of=as_of)
    assert result.level == LEVEL_REVIEW
    assert result.should_notify() is True
    store.close()


def test_one_structural_escalates_on_its_own(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    ticker = _held()
    as_of = date(2026, 8, 17)
    _touch(store, ticker, "Promoter holding falls or pledge rises", when=as_of)
    result = escalate(ticker, store, as_of=as_of)
    assert result.level == LEVEL_REVIEW
    assert result.should_notify() is True
    store.close()


def test_material_older_than_two_quarters_drops_out(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    ticker = _held()
    as_of = date(2026, 8, 17)
    stale = as_of - WINDOW - timedelta(days=1)
    _touch(store, ticker, "Order inflow stops growing", when=stale)
    _touch(store, ticker, "Working capital deteriorates", when=as_of)
    result = escalate(ticker, store, as_of=as_of)
    assert result.material == 1
    assert result.level == LEVEL_RECORD
    assert result.should_notify() is False
    store.close()


def test_manual_condition_counts_toward_escalation_not_s(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    ticker = parse_ticker(
        {
            "symbol": "FOO",
            "bse_code": "1",
            "thesis": "why we own it",
            "conditions": [
                {"text": "Moat erodes", "check": "manual", "severity": "material"},
                {
                    "text": "Order inflow stops growing",
                    "check": "quantitative",
                    "kpi": "order_inflow_ttm",
                    "severity": "material",
                },
            ],
        }
    )
    as_of = date(2026, 8, 17)
    _touch(store, ticker, "Moat erodes", when=as_of)
    _touch(store, ticker, "Order inflow stops growing", when=as_of)
    result = escalate(ticker, store, as_of=as_of)
    assert result.level == LEVEL_REVIEW
    payload = {
        "kpis": [
            {
                "name": "revenue",
                "found": True,
                "value": 130,
                "prior_value": 100,
                "period": "Q1",
            }
        ],
        "order": {"found": True, "value": 200, "q_sales": 100},
        "guidance": {"touches_named_kpi": True, "direction": 1},
    }
    manual_only = parse_ticker(
        {
            "symbol": "BAR",
            "bse_code": "2",
            "thesis": "why we own it",
            "conditions": [
                {"text": "Moat erodes", "check": "manual", "severity": "material"}
            ],
        }
    )
    scored_manual = score_extraction(payload, ticker=manual_only)
    assert scored_manual.x["kpi"] is None
    assert scored_manual.x["book"] is None
    assert scored_manual.S is None
    store.close()
