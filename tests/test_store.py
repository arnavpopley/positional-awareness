from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.filter import classify
from src.main import ingest
from src.sources.base import Filing
from src.sources.bse import load_fixture
from src.store import Store
from tests.helpers import filing

IST = ZoneInfo("Asia/Kolkata")
REAL = Path("tests/fixtures/suzlon_real_50.json")


def test_dedupe_on_ann_id(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    f = Filing(
        ticker="SUZLON",
        exchange="BSE",
        ann_id="abc",
        category="Board Meeting",
        subcategory="Board Meeting",
        headline="Board Meeting Intimation",
        pdf_url="https://example.test/a.pdf",
        filed_at=datetime(2026, 7, 20, tzinfo=IST),
    )
    assert store.insert_filing(f, "candidate") is not None
    assert store.insert_filing(f, "candidate") is None
    f2 = Filing(
        ticker="SUZLON",
        exchange="BSE",
        ann_id="abc",
        category="Board Meeting",
        subcategory="Board Meeting",
        headline="Board Meeting Intimation",
        pdf_url="https://example.test/other.pdf",
        filed_at=datetime(2026, 7, 20, tzinfo=IST),
    )
    assert store.insert_filing(f2, "candidate") is None
    store.close()


def test_dedupe_on_pdf_when_no_ann_id(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    f = Filing(
        ticker="SUZLON",
        exchange="BSE",
        ann_id=None,
        category="Result",
        subcategory="Financial Results",
        headline="Results",
        pdf_url="https://example.test/r.pdf",
        filed_at=None,
    )
    assert store.insert_filing(f, "candidate") is not None
    assert store.insert_filing(f, "candidate") is None
    store.close()


def test_stale_candidate_stored_without_notification(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    now = datetime(2026, 8, 16, 12, 0, tzinfo=IST)
    stale = filing(
        headline="Board Meeting Intimation for unaudited financial results",
        category="Board Meeting",
        subcategory="Board Meeting",
        filed_at=now - timedelta(days=30),
        ann_id="stale-30d",
    )
    notified: list[str] = []

    def capture(item: Filing, status: str = "candidate") -> bool:
        notified.append(item.headline)
        return True

    stats = ingest([stale], store, notify=True, notifier=capture, now=now)
    assert classify(stale) == "candidate"
    assert stats["candidate"] == 1
    assert stats["notified"] == 0
    assert notified == []
    row = store.conn.execute(
        "SELECT filter_status FROM filings WHERE ann_id = 'stale-30d'"
    ).fetchone()
    assert row["filter_status"] == "candidate"
    store.close()


def test_fresh_candidate_still_notifies(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    now = datetime(2026, 8, 16, 12, 0, tzinfo=IST)
    fresh = filing(
        headline="Board Meeting Intimation for unaudited financial results",
        category="Board Meeting",
        subcategory="Board Meeting",
        filed_at=now - timedelta(hours=2),
        ann_id="fresh-2h",
    )
    notified: list[str] = []

    def capture(item: Filing, status: str = "candidate") -> bool:
        notified.append(item.headline)
        return True

    stats = ingest([fresh], store, notify=True, notifier=capture, now=now)
    assert stats["candidate"] == 1
    assert stats["notified"] == 1
    store.close()


def test_notify_backfill_cannot_bypass_recency(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    now = datetime(2026, 8, 16, 12, 0, tzinfo=IST)
    stale = filing(
        headline="Board Meeting Intimation for unaudited financial results",
        category="Board Meeting",
        subcategory="Board Meeting",
        filed_at=now - timedelta(days=30),
        ann_id="stale-backfill",
    )
    notified: list[str] = []

    def capture(item: Filing, status: str = "candidate") -> bool:
        notified.append(item.headline)
        return True

    stats = ingest([stale], store, notify=True, notifier=capture, now=now)
    assert stats["notified"] == 0
    store.close()


def test_july_2026_results_and_outcome_collapse_to_one_notify(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    all_filings = load_fixture(REAL, "SUZLON")
    pair = [
        f
        for f in all_filings
        if "28Th July 2026" in f.headline or "28th July 2026" in f.headline
        if f.subcategory in {"Financial Results", "Outcome of Board Meeting"}
    ]
    assert len(pair) == 2
    cats = {f.subcategory for f in pair}
    assert cats == {"Financial Results", "Outcome of Board Meeting"}
    notified: list[tuple[str, str]] = []

    def capture(item: Filing, status: str = "candidate") -> bool:
        notified.append((item.subcategory, item.headline))
        return True

    now = datetime(2026, 7, 28, 18, 0, tzinfo=IST)
    stats = ingest(pair, store, notify=True, notifier=capture, now=now)
    assert stats["candidate"] == 2
    assert stats["collapsed"] == 1
    assert stats["notified"] == 1
    assert notified == [
        ("Financial Results", "Outcome Of The Board Meeting Dated 28Th July 2026.")
    ]
    collapsed = store.conn.execute(
        "SELECT subcategory, collapsed_into FROM filings WHERE collapsed_into IS NOT NULL"
    ).fetchall()
    assert len(collapsed) == 1
    assert collapsed[0]["subcategory"] == "Outcome of Board Meeting"
    results_id = store.conn.execute(
        "SELECT id FROM filings WHERE subcategory = 'Financial Results'"
    ).fetchone()["id"]
    assert collapsed[0]["collapsed_into"] == results_id
    store.close()


def test_fixture_trading_window_killed_not_notified(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    filings = load_fixture(REAL, "SUZLON")
    notified: list[str] = []

    def capture(item: Filing, status: str = "candidate") -> bool:
        notified.append(item.headline)
        return True

    now = datetime(2026, 8, 16, 12, 0, tzinfo=IST)
    ingest(filings, store, notify=True, notifier=capture, now=now)
    killed = store.conn.execute(
        "SELECT headline, subcategory FROM filings WHERE filter_status = 'kill'"
    ).fetchall()
    assert any("Trading Window" in (row["subcategory"] or "") for row in killed)
    assert not any("trading window" in h.lower() for h in notified)
    store.close()
