from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.extract import (
    SYSTEM_PROMPT,
    ExtractError,
    extract_filing,
    gemini_extract,
    is_near_empty,
    pages_from_pdf,
    select_text,
)
from src.ledger import load_tickers
from src.main import ingest
from src.store import Store
from tests.helpers import filing, make_pdf

IST = ZoneInfo("Asia/Kolkata")
SECRET = "gemini-test-key-do-not-leak-7c1e"


def _results(**kwargs):
    now = kwargs.pop("now", datetime(2026, 8, 16, 12, 0, tzinfo=IST))
    return filing(
        headline="Financial Results for the quarter",
        category="Result",
        subcategory="Financial Results",
        filed_at=now - timedelta(hours=2),
        ann_id=kwargs.pop("ann_id", "fr-1"),
        **kwargs,
    )


def test_select_text_keeps_first_pages_and_kpi_hits():
    pages = ["cover", "p2", "p3", "unrelated", "deliveries 1500 MW", "tail"]
    text = select_text(pages, ["deliveries"], first_pages=3)
    assert "cover" in text and "p3" in text
    assert "deliveries 1500 MW" in text
    assert "unrelated" not in text
    assert "tail" not in text


def test_select_text_caps_at_15k():
    pages = ["a" * 20_000, "deliveries"]
    text = select_text(pages, ["deliveries"], max_chars=15_000, first_pages=1)
    assert len(text) == 15_000


def test_near_empty():
    assert is_near_empty("   \n\t  ")
    assert is_near_empty("x" * 20)
    assert is_near_empty("Page 1")
    assert not is_near_empty("Quarterly deliveries 1500 MW")


def test_system_prompt_is_spec_section_9_verbatim():
    spec = Path("SPEC.md").read_text(encoding="utf-8")
    start = spec.index("## 9. Prompt guardrails")
    end = spec.index("## 10.")
    bullets = [
        line
        for line in spec[start:end].splitlines()
        if line.startswith("- ")
    ]
    assert len(bullets) == 4
    for bullet in bullets:
        assert bullet in SYSTEM_PROMPT


def test_pdfplumber_reads_kpi_pdf(tmp_path: Path):
    path = tmp_path / "kpi.pdf"
    path.write_bytes(make_pdf("Quarterly deliveries 1500 MW order book 3.2 GW"))
    pages = pages_from_pdf(path)
    blob = " ".join(pages)
    assert "1500" in blob
    assert "deliveries" in blob.lower()


def test_near_empty_pdf_sets_manual_read_and_skips_llm(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    calls: list[str] = []

    def llm(prompt: str) -> dict:
        calls.append(prompt)
        raise AssertionError("Gemini must not run on near-empty text")

    result = extract_filing(
        _results(ann_id="empty-pdf"),
        None,
        store,
        pdf_bytes=make_pdf("   "),
        pdf_dir=tmp_path / "pdfs",
        llm=llm,
    )
    assert result.needs_manual_read is True
    assert result.kpis_json is None
    assert calls == []
    store.close()


def test_cache_prevents_second_gemini_call(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    ticker = load_tickers(Path("config/tickers.example.yaml"))[0]
    calls: list[str] = []

    def llm(prompt: str) -> dict:
        calls.append(prompt)
        return {
            "kpis": [
                {
                    "name": "deliveries_mw",
                    "found": True,
                    "value": 1500,
                    "quote": "Quarterly deliveries 1500 MW",
                }
            ]
        }

    item = _results(ann_id="cache-1")
    pdf = make_pdf("Quarterly deliveries 1500 MW")
    first = extract_filing(
        item, ticker, store, pdf_bytes=pdf, pdf_dir=tmp_path / "pdfs", llm=llm
    )
    second = extract_filing(
        item, ticker, store, pdf_bytes=pdf, pdf_dir=tmp_path / "pdfs", llm=llm
    )
    assert first.cached is False
    assert second.cached is True
    assert len(calls) == 1
    assert first.kpis_json["kpis"][0]["value"] == 1500
    store.close()


def test_gemini_token_not_in_exception_or_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    from google import genai

    def boom(*args, **kwargs):
        raise RuntimeError(f"quota exceeded token={SECRET}")

    monkeypatch.setattr(genai, "Client", boom)
    with pytest.raises(ExtractError) as caught:
        gemini_extract("prompt", api_key=SECRET)
    assert SECRET not in str(caught.value)
    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err


def test_ingest_skips_stale_and_kill(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    now = datetime(2026, 8, 16, 12, 0, tzinfo=IST)
    seen: list[str] = []

    def spy(item, ticker, store):
        seen.append(item.ann_id)
        return None

    stale = filing(
        headline="Financial Results",
        category="Result",
        subcategory="Financial Results",
        filed_at=now - timedelta(days=10),
        ann_id="stale-extract",
    )
    killed = filing(
        headline="Trading Window closure",
        category="Insider Trading / SAST",
        subcategory="Closure of Trading Window",
        filed_at=now - timedelta(hours=1),
        ann_id="kill-extract",
    )
    ingest([stale, killed], store, notify=True, extractor=spy, now=now)
    assert seen == []
    store.close()


def test_ingest_skips_collapsed_outcome(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    now = datetime(2026, 7, 28, 18, 0, tzinfo=IST)
    seen: list[str] = []

    def spy(item, ticker, store):
        seen.append(item.subcategory)
        return None

    outcome = filing(
        headline="Outcome Of The Board Meeting Dated 28Th July 2026.",
        category="Board Meeting",
        subcategory="Outcome of Board Meeting",
        filed_at=now,
        ann_id="out-1",
        pdf_url="https://example.test/outcome.pdf",
    )
    results = filing(
        headline="Outcome Of The Board Meeting Dated 28Th July 2026.",
        category="Result",
        subcategory="Financial Results",
        filed_at=now,
        ann_id="res-1",
        pdf_url="https://example.test/results.pdf",
    )
    ingest([outcome, results], store, notify=True, extractor=spy, now=now)
    assert seen == ["Financial Results"]
    store.close()


def test_ingest_extracts_fresh_candidate_once(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    now = datetime(2026, 8, 16, 12, 0, tzinfo=IST)
    seen: list[str] = []

    def spy(item, ticker, store):
        seen.append(item.ann_id)
        return None

    fresh = _results(now=now, ann_id="fresh-extract")
    ingest([fresh], store, notify=True, extractor=spy, now=now)
    ingest([fresh], store, notify=True, extractor=spy, now=now)
    assert seen == ["fresh-extract"]
    store.close()
