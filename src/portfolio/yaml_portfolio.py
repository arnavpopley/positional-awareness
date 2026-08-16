from __future__ import annotations

import sys
from pathlib import Path

from src.ledger import load_tickers
from src.paths import TICKERS_PATH
from src.portfolio.base import Holding, Portfolio


class YamlPortfolio(Portfolio):
    """Ledger as a portfolio. Default source; no Groww credential required."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or TICKERS_PATH

    def fetch(self) -> list[Holding]:
        return [
            Holding(
                symbol=t.symbol,
                isin=t.isin,
                qty=t.qty,
                avg_cost=t.avg_cost,
            )
            for t in load_tickers(self.path)
        ]


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    path = Path(args[0]) if args else None
    for h in YamlPortfolio(path).fetch():
        print(f"{h.symbol}\tqty={h.qty}\tcost={h.avg_cost}\tisin={h.isin or '—'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
