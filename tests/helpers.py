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
    filed_at: datetime | None = None,
    ann_id: str | None = None,
) -> Filing:
    return Filing(
        ticker=ticker,
        exchange="BSE",
        ann_id=ann_id if ann_id is not None else "x",
        category=category,
        subcategory=subcategory,
        headline=headline,
        pdf_url="https://example.test/a.pdf",
        filed_at=filed_at if filed_at is not None else datetime(2026, 7, 28, 14, 0, tzinfo=IST),
        detail=detail,
    )
