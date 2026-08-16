from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import requests
from dotenv import load_dotenv

from src.ledger import Ticker
from src.paths import DATA_DIR, ROOT
from src.sources.base import Filing
from src.sources.bse import HEADERS, TIMEOUT
from src.store import Store, filing_hash

# SPEC.md §9 — verbatim in the Gemini system prompt.
SYSTEM_PROMPT = """- You never place a trade. You never output an action verb (including buy, sell, add, trim, hold). Report factor evidence and figures only.
- If the filing does not touch any listed KPI/condition, that factor is **inactive** (n/a), not x = 0. Do not invent a thesis.
- Numbers over adjectives. Quote figures from the filing.
- Output JSON only for extract/score calls."""

MODEL = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
MAX_CHARS = 15_000
FIRST_PAGES = 3
PDF_DIR = DATA_DIR / "pdfs"

EXTRACT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "kpis": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "found": {"type": "boolean"},
                    "period": {"type": "string"},
                    "value": {"type": "number"},
                    "unit": {"type": "string"},
                    "quote": {"type": "string"},
                    "prior_period": {"type": "string"},
                    "prior_value": {"type": "number"},
                },
                "required": ["name", "found"],
            },
        },
        "order": {
            "type": "object",
            "properties": {
                "found": {"type": "boolean"},
                "value": {"type": "number"},
                "unit": {"type": "string"},
                "quote": {"type": "string"},
            },
        },
        "guidance": {
            "type": "object",
            "properties": {
                "touches_named_kpi": {"type": "boolean"},
                "direction": {"type": "integer"},
                "quote": {"type": "string"},
            },
        },
    },
    "required": ["kpis"],
}


class ExtractError(RuntimeError):
    """PDF or Gemini extract failed. Must never contain API keys."""


@dataclass(frozen=True)
class Extraction:
    filing_hash: str
    text: str
    needs_manual_read: bool
    kpis_json: dict | None
    cached: bool
    model: str | None = None


def kpi_keywords(ticker: Ticker | None) -> list[str]:
    if ticker is None:
        return []
    keys: list[str] = []
    for kpi in ticker.kpis:
        keys.append(kpi.label)
        keys.append(kpi.name.replace("_", " "))
        keys.extend(part for part in re.split(r"[_\s]+", kpi.name) if len(part) > 2)
        keys.extend(part for part in kpi.label.split() if len(part) > 2)
    seen: set[str] = set()
    out: list[str] = []
    for key in keys:
        folded = key.strip().lower()
        if folded and folded not in seen:
            seen.add(folded)
            out.append(key.strip())
    return out


def page_matches(page: str, keywords: list[str]) -> bool:
    blob = page.lower()
    return any(key.lower() in blob for key in keywords)


def select_text(
    pages: list[str],
    keywords: list[str],
    *,
    max_chars: int = MAX_CHARS,
    first_pages: int = FIRST_PAGES,
) -> str:
    """First pages plus any page matching a KPI keyword, capped at ~15k chars."""
    chosen: list[str] = []
    used: set[int] = set()

    def add(index: int) -> None:
        if index in used or not (0 <= index < len(pages)):
            return
        used.add(index)
        chosen.append(pages[index])

    for i in range(min(first_pages, len(pages))):
        add(i)
    for i, page in enumerate(pages):
        if page_matches(page, keywords):
            add(i)
    text = "\n\n".join(part for part in chosen if part)
    if len(text) > max_chars:
        return text[:max_chars]
    return text


def is_near_empty(text: str) -> bool:
    """Image-only / scanned PDFs, not a short but real KPI line."""
    tokens = re.findall(r"[A-Za-z0-9]{2,}", text)
    return len(tokens) < 4


def pages_from_pdf(path: Path) -> list[str]:
    import pdfplumber

    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return pages


def _redact(text: str, secret: str) -> str:
    if secret and secret in text:
        return text.replace(secret, "<redacted>")
    return text


def _api_key() -> str:
    load_dotenv(ROOT / ".env")
    return os.environ.get("GEMINI_API_KEY") or ""


def download_pdf(
    url: str,
    dest: Path,
    *,
    session: requests.Session | None = None,
    timeout: int = TIMEOUT,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    client = session or requests.Session()
    response = client.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    dest.write_bytes(response.content)
    return dest


def _user_prompt(filing: Filing, ticker: Ticker | None, text: str) -> str:
    kpis = []
    thesis = ""
    if ticker is not None:
        thesis = ticker.thesis
        kpis = [
            {"name": k.name, "label": k.label, "check": k.check} for k in ticker.kpis
        ]
    payload = {
        "ticker": filing.ticker,
        "headline": filing.headline,
        "category": filing.category,
        "subcategory": filing.subcategory,
        "thesis": thesis,
        "named_kpis": kpis,
        "filing_text": text,
    }
    return (
        "Extract figures for the named KPIs from this filing. "
        "If a KPI is not in the text, set found=false and omit invented numbers. "
        "guidance.direction is -1, 0, or 1 only when the filing names a listed KPI; else omit. "
        "JSON only.\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def gemini_extract(user_prompt: str, *, api_key: str | None = None) -> dict:
    key = api_key if api_key is not None else _api_key()
    if not key:
        raise ExtractError("GEMINI_API_KEY is missing")
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model=MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0,
                response_mime_type="application/json",
                response_schema=EXTRACT_SCHEMA,
            ),
        )
        raw = response.text or "{}"
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ExtractError("Gemini returned non-object JSON")
        return parsed
    except ExtractError:
        raise
    except Exception as exc:
        raise ExtractError(_redact(f"Gemini extract failed: {exc}", key)) from None


def extract_filing(
    filing: Filing,
    ticker: Ticker | None,
    store: Store,
    *,
    pdf_bytes: bytes | None = None,
    pdf_dir: Path | None = None,
    llm=None,
    session: requests.Session | None = None,
) -> Extraction:
    """One Gemini call per filing. Cached by filing hash. Not called per poll."""
    key = filing_hash(filing)
    cached = store.get_extraction(key)
    if cached is not None:
        payload = json.loads(cached["kpis_json"]) if cached["kpis_json"] else None
        return Extraction(
            filing_hash=key,
            text=cached["text"] or "",
            needs_manual_read=bool(cached["needs_manual_read"]),
            kpis_json=payload,
            cached=True,
            model=cached["model"],
        )

    text = ""
    needs_manual = False
    kpis_json: dict | None = None
    model: str | None = None
    dest_dir = pdf_dir or PDF_DIR
    pdf_path = dest_dir / f"{key}.pdf"
    try:
        if pdf_bytes is not None:
            dest_dir.mkdir(parents=True, exist_ok=True)
            pdf_path.write_bytes(pdf_bytes)
        elif filing.pdf_url:
            download_pdf(filing.pdf_url, pdf_path, session=session)
        else:
            needs_manual = True
        if not needs_manual and pdf_path.exists():
            pages = pages_from_pdf(pdf_path)
            text = select_text(pages, kpi_keywords(ticker))
            if is_near_empty(text):
                needs_manual = True
        elif not needs_manual:
            needs_manual = True
    except Exception:
        needs_manual = True

    if not needs_manual:
        prompt = _user_prompt(filing, ticker, text)
        try:
            if llm is not None:
                kpis_json = llm(prompt)
            else:
                kpis_json = gemini_extract(prompt)
            model = MODEL
        except ExtractError:
            needs_manual = True

    store.save_extraction(
        filing_hash=key,
        filing_id=None,
        text=text,
        needs_manual_read=needs_manual,
        kpis_json=kpis_json,
        model=model,
    )
    return Extraction(
        filing_hash=key,
        text=text,
        needs_manual_read=needs_manual,
        kpis_json=kpis_json,
        cached=False,
        model=model,
    )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m src.extract PATH.pdf", file=sys.stderr)
        return 2
    path = Path(args[0])
    if not path.exists():
        print(f"extract: missing {path}", file=sys.stderr)
        return 1
    pages = pages_from_pdf(path)
    text = select_text(pages, [])
    flag = " needs_manual_read" if is_near_empty(text) else ""
    print(f"pages={len(pages)} chars={len(text)}{flag}")
    print(text[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
