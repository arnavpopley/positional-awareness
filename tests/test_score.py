from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from src.ledger import Kpi, Ticker
from src.main import ingest
from src.score import (
    WEIGHTS,
    active,
    band_for,
    book_factor,
    guidance_factor,
    industry_factor,
    kpi_factor,
    naive_weighted_sum,
    persist,
    score,
    score_extraction,
)
from src.store import Store
from tests.helpers import filing

IST = ZoneInfo("Asia/Kolkata")

FORBIDDEN = ("add", "trim", "buy", "sell")


def test_order_win_only_reaches_strongly_positive_band():
    result = score(book=active(1.0, raw=1.0))
    assert result.S == 1.0
    assert result.S >= 0.60
    assert band_for(result.S) == "strongly positive"
    assert result.active_factors == ("book",)


def test_zero_active_factors_undefined():
    result = score()
    assert result.S is None
    assert result.band is None
    assert result.active_factors == ()
    assert all(line.endswith("n/a") for line in result.lines)


def test_single_active_factor_low_confidence_suppresses_band():
    result = score(book=active(1.0))
    assert result.low_confidence is True
    assert result.band is None
    assert "n/a" in result.display()
    assert "0.00" not in "".join(line for line in result.lines if line.endswith("n/a"))


def test_all_five_active_matches_naive_sum():
    xs = dict(kpi=0.4, book=-0.2, industry=0.0, price=0.8, guidance=-1.0)
    result = score(
        kpi=active(xs["kpi"]),
        book=active(xs["book"]),
        industry=active(xs["industry"]),
        price=active(xs["price"]),
        guidance=active(xs["guidance"]),
    )
    naive = naive_weighted_sum(**xs)
    assert result.S == naive
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-12
    assert result.low_confidence is False
    assert result.band == band_for(naive)
    assert result.active_factors == ("kpi", "book", "industry", "price", "guidance")


def test_inactive_lines_are_na_not_zero():
    result = score(book=active(0.5), price=active(-0.5))
    na_lines = [line for line in result.lines if ": n/a" in line]
    assert len(na_lines) == 3
    for line in result.lines:
        if not line.endswith("n/a"):
            continue
        assert "0.00" not in line
        assert "0.0" not in line


def test_persist_active_factors(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    result = score(book=active(1.0), price=active(0.2))
    row_id = persist(result, store, filing_id=None)
    row = store.conn.execute("SELECT * FROM scores WHERE id = ?", (row_id,)).fetchone()
    assert row["active_factors"] == "book,price"
    assert row["S"] == result.S
    assert row["low_confidence"] == 0
    store.close()


def test_no_action_verbs_in_src_output_strings():
    verb = re.compile(r"\b(" + "|".join(FORBIDDEN) + r")\b", re.I)
    hits: list[str] = []
    for path in Path("src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value
                if "CREATE TABLE" in text or "ALTER TABLE" in text:
                    continue
                if "You never output an action verb" in text:
                    continue
                if verb.search(text):
                    hits.append(f"{path}:{node.lineno}:{text!r}")
    assert hits == []


def _ticker(symbol: str = "SUZLON", sector: str | None = "renewables") -> Ticker:
    return Ticker(
        symbol=symbol,
        bse_code="532667",
        nse_symbol=symbol,
        status="held",
        sector=sector,
        qty=1.0,
        avg_cost=10.0,
        confidence=70,
        review_by=None,
        thesis="placeholder thesis for tests",
        kpis=(Kpi(name="revenue", label="Revenue", check="qoq"),),
    )


def _results(**kwargs):
    now = kwargs.pop("now", datetime(2026, 8, 16, 12, 0, tzinfo=IST))
    return filing(
        headline="Financial Results for the quarter",
        category="Result",
        subcategory="Financial Results",
        filed_at=now - timedelta(hours=2),
        ann_id=kwargs.pop("ann_id", "fr-score"),
        **kwargs,
    )


def test_kpi_qoq_winsorize_to_x():
    payload = {
        "kpis": [
            {
                "name": "revenue",
                "found": True,
                "value": 130,
                "prior_value": 100,
                "period": "Q1FY27",
            }
        ]
    }
    factor = kpi_factor(payload)
    assert factor.active is True
    assert factor.raw == 0.30
    assert factor.value == 1.0


def test_kpi_without_prior_is_inactive():
    payload = {
        "kpis": [
            {"name": "revenue", "found": True, "value": 130, "prior_value": None, "period": "Q1"}
        ]
    }
    assert kpi_factor(payload).active is False
    result = score_extraction(payload)
    assert result.x["kpi"] is None


def test_book_order_over_quarterly_sales():
    payload = {"order": {"found": True, "value": 500, "q_sales": 400}}
    factor = book_factor(payload)
    assert factor.active is True
    assert factor.raw == 1.25
    assert factor.value == 1.0


def test_book_named_kpi_qoq():
    payload = {
        "kpis": [
            {
                "name": "order book",
                "found": True,
                "value": 120,
                "prior_value": 100,
                "period": "Q1",
            }
        ]
    }
    factor = book_factor(payload)
    assert factor.active is True
    assert abs(factor.raw - 0.20) < 1e-12
    assert abs(factor.value - 0.80) < 1e-12
    assert kpi_factor(payload).active is False


def test_guidance_maps_to_signed_unit():
    up = {"guidance": {"touches_named_kpi": True, "direction": 1}}
    down = {"guidance": {"touches_named_kpi": True, "direction": -1}}
    skip = {"guidance": {"touches_named_kpi": False, "direction": 1}}
    assert guidance_factor(up).value == 1.0
    assert guidance_factor(down).value == -1.0
    assert guidance_factor(skip).active is False


def test_needs_manual_read_suppresses_band():
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
    }
    confirmed = score_extraction(payload)
    assert confirmed.band == "strongly positive"
    flagged = score_extraction(payload, needs_manual_read=True)
    assert flagged.S == confirmed.S
    assert flagged.band is None


def test_industry_inactive_without_peer_history(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    own = _ticker("SUZLON")
    peer = _ticker("PEER")
    assert industry_factor(own, [own, peer], store).active is False
    assert industry_factor(own, [], store).active is False
    store.close()


def test_industry_z_from_peer_kpi_series(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    own = _ticker("SUZLON")
    peer = _ticker("PEER")
    for i, value in enumerate([100.0, 110.0, 90.0, 150.0]):
        store.insert_kpi_print(
            ticker="PEER",
            kpi_name="revenue",
            period=f"Q{i}",
            value=value,
            source_filing_id=None,
        )
    factor = industry_factor(own, [own, peer], store)
    assert factor.active is True
    store.close()


def test_ingest_persists_score_from_extract_json(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    now = datetime(2026, 8, 16, 12, 0, tzinfo=IST)
    payload = {
        "kpis": [
            {
                "name": "revenue",
                "found": True,
                "value": 130,
                "prior_value": 100,
                "period": "Q1FY27",
            }
        ],
        "order": {"found": True, "value": 200, "q_sales": 100},
        "guidance": {"touches_named_kpi": False, "direction": 0},
    }

    def extractor(item, ticker, db):
        return SimpleNamespace(cached=False, needs_manual_read=False, kpis_json=payload)

    stats = ingest(
        [_results(now=now, ann_id="score-in")],
        store,
        notify=False,
        now=now,
        tickers=[_ticker()],
        extractor=extractor,
    )
    assert stats["extracted"] == 1
    assert stats["scored"] == 1
    row = store.conn.execute("SELECT * FROM scores").fetchone()
    assert row["S"] == 1.0
    assert row["band"] == "strongly positive"
    assert row["active_factors"] == "kpi,book"
    prints = store.conn.execute("SELECT * FROM kpi_series").fetchall()
    assert len(prints) == 1
    assert prints[0]["value"] == 130
    store.close()


def test_ingest_manual_read_persists_without_band(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    now = datetime(2026, 8, 16, 12, 0, tzinfo=IST)
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
    }

    def extractor(item, ticker, db):
        return SimpleNamespace(cached=False, needs_manual_read=True, kpis_json=payload)

    stats = ingest(
        [_results(now=now, ann_id="score-manual")],
        store,
        notify=False,
        now=now,
        tickers=[_ticker()],
        extractor=extractor,
    )
    assert stats["needs_manual_read"] == 1
    row = store.conn.execute("SELECT * FROM scores").fetchone()
    assert row["S"] == 1.0
    assert row["band"] is None
    assert json.loads(row["triage_json"])["needs_manual_read"] is True
    store.close()


def test_ingest_skips_scoring_when_extractor_returns_none(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    now = datetime(2026, 8, 16, 12, 0, tzinfo=IST)
    stats = ingest(
        [_results(now=now, ann_id="score-skip")],
        store,
        notify=False,
        now=now,
        extractor=lambda *args, **kwargs: None,
    )
    assert stats["extracted"] == 0
    assert stats["scored"] == 0
    n = store.conn.execute("SELECT COUNT(*) AS n FROM scores").fetchone()["n"]
    assert n == 0
    store.close()


def test_manual_condition_never_activates_scoring_factor():
    from src.ledger import parse_ticker

    ticker = parse_ticker(
        {
            "symbol": "FOO",
            "bse_code": "1",
            "thesis": "why we own it",
            "conditions": [{"text": "Moat erodes, story stops making sense", "check": "manual"}],
        }
    )
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
    result = score_extraction(payload, ticker=ticker)
    assert result.x["kpi"] is None
    assert result.x["book"] is None
    assert result.x["guidance"] is None
    assert result.S is None
    assert result.band is None
