from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.main import ingest
from src.sources.base import Filing
from src.sources.bse import load_fixture
from src.store import Store

IST = ZoneInfo("Asia/Kolkata")


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


def test_fixture_ingest_kills_trading_window_and_notifies_candidates(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    filings = load_fixture(Path("tests/fixtures/anngetdata.json"), "SUZLON")
    notified: list[str] = []

    def capture(filing: Filing) -> bool:
        notified.append(filing.headline)
        return True

    stats = ingest(filings, store, notify=True, notifier=capture)
    assert stats["kill"] >= 1
    assert stats["candidate"] >= 1
    assert stats["notified"] == stats["candidate"]

    killed = store.conn.execute(
        "SELECT headline, subcategory FROM filings WHERE filter_status = 'kill'"
    ).fetchall()
    assert any("Trading Window" in (row["subcategory"] or "") for row in killed)
    assert not any("trading window" in h.lower() for h in notified)
    assert any("Board Meeting Intimation" in h for h in notified)
    assert any("result" in h.lower() or "board meeting" in h.lower() for h in notified)
    store.close()
