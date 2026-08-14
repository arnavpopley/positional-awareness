from datetime import datetime
from zoneinfo import ZoneInfo

from src.sources.base import Filing

IST = ZoneInfo("Asia/Kolkata")


def filing(
    *,
    headline: str,
    category: str = "",
    subcategory: str = "",
    detail: str = "",
    ticker: str = "SUZLON",
) -> Filing:
    return Filing(
        ticker=ticker,
        exchange="BSE",
        ann_id="x",
        category=category,
        subcategory=subcategory,
        headline=headline,
        pdf_url="https://example.test/a.pdf",
        filed_at=datetime(2026, 7, 28, 14, 0, tzinfo=IST),
        detail=detail,
    )
