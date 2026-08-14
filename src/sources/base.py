from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.ledger import Ticker


@dataclass(frozen=True)
class Filing:
    ticker: str
    exchange: str
    ann_id: str | None
    category: str
    subcategory: str
    headline: str
    pdf_url: str | None
    filed_at: datetime | None
    detail: str = ""

    def dedupe_key(self) -> tuple[str, str]:
        if self.ann_id:
            return (self.exchange, f"id:{self.ann_id}")
        if self.pdf_url:
            return (self.exchange, f"pdf:{self.pdf_url}")
        raise ValueError("Filing has neither ann_id nor pdf_url")


class Source(ABC):
    @abstractmethod
    def fetch(self, ticker: Ticker, since: datetime) -> list[Filing]:
        """Return filings for ticker on or after `since`."""
