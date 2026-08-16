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
    pdf_url: str | None = "https://example.test/a.pdf",
) -> Filing:
    return Filing(
        ticker=ticker,
        exchange="BSE",
        ann_id=ann_id if ann_id is not None else "x",
        category=category,
        subcategory=subcategory,
        headline=headline,
        pdf_url=pdf_url,
        filed_at=filed_at if filed_at is not None else datetime(2026, 7, 28, 14, 0, tzinfo=IST),
        detail=detail,
    )


def make_pdf(text: str) -> bytes:
    """Minimal one-page PDF whose content stream pdfplumber can read."""

    def esc(value: str) -> str:
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    stream = f"BT /F1 12 Tf 72 720 Td ({esc(text)}) Tj ET".encode("latin-1", "replace")
    objs = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        (
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
        ),
        b"4 0 obj << /Length %d >> stream\n" % len(stream) + stream + b"\nendstream\nendobj\n",
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
    ]
    header = b"%PDF-1.4\n"
    offsets = [0]
    body = b""
    pos = len(header)
    for obj in objs:
        offsets.append(pos)
        body += obj
        pos += len(obj)
    xref = f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets[1:]:
        xref += f"{off:010d} 00000 n \n".encode()
    startxref = len(header) + len(body)
    trailer = (
        f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{startxref}\n%%EOF\n"
    ).encode()
    return header + body + xref + trailer

