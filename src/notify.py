from __future__ import annotations

import json
import subprocess
import sys
from shutil import which

from src.sources.base import Filing

CHANNEL = "macos"


def _as_literal(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def notify_candidate(filing: Filing) -> bool:
    """macOS notification: headline + link. Candidate filings only."""
    title = f"{filing.ticker} · candidate"
    body = " ".join(filing.headline.split())
    if filing.pdf_url:
        body = f"{body} · {filing.pdf_url}"
    if len(body) > 220:
        body = body[:219] + "…"
    if sys.platform != "darwin" or which("osascript") is None:
        print(f"notify skipped ({title}): {body}")
        return False
    script = (
        f"display notification {_as_literal(body)} "
        f"with title {_as_literal(title)}"
    )
    result = subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def main(argv: list[str] | None = None) -> int:
    del argv
    demo = Filing(
        ticker="TEST",
        exchange="BSE",
        ann_id="demo",
        category="Board Meeting",
        subcategory="Board Meeting",
        headline="Board Meeting Intimation for unaudited financial results",
        pdf_url="https://www.bseindia.com/corporates/ann.html",
        filed_at=None,
    )
    ok = notify_candidate(demo)
    print("sent" if ok else "not sent")
    return 0 if ok or sys.platform != "darwin" else 1


if __name__ == "__main__":
    raise SystemExit(main())
