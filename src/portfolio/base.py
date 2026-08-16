from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Holding:
    symbol: str
    isin: str
    qty: float
    avg_cost: float


class Portfolio(ABC):
    @abstractmethod
    def fetch(self) -> list[Holding]:
        """Current holdings. Implementations must not place orders."""


def main(argv: list[str] | None = None) -> int:
    del argv
    print("Holding(symbol, isin, qty, avg_cost); Portfolio.fetch() -> list[Holding]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
