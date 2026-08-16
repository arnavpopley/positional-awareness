from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import yaml

from src.paths import TICKERS_EXAMPLE_PATH, TICKERS_PATH

VALID_STATUS = {"held", "watchlist"}


class LedgerError(ValueError):
    """Invalid tickers.yaml — refuse to watch."""


@dataclass(frozen=True)
class Kpi:
    name: str
    label: str
    check: str


@dataclass(frozen=True)
class Ticker:
    symbol: str
    bse_code: str
    nse_symbol: str | None
    status: str
    sector: str | None
    qty: float
    avg_cost: float
    confidence: int
    review_by: date | None
    thesis: str
    kpis: tuple[Kpi, ...]
    results_due: date | None = None
    isin: str = ""

    def thesis_short(self, width: int = 48) -> str:
        line = " ".join(self.thesis.split())
        if len(line) <= width:
            return line
        return line[: width - 1] + "…"


def _as_date(value: object, field: str, symbol: str) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise LedgerError(f"{symbol}: {field} must be YYYY-MM-DD")


def _require_str(row: dict, key: str, symbol: str) -> str:
    value = row.get(key)
    if value is None or not str(value).strip():
        raise LedgerError(f"{symbol}: missing {key}")
    return str(value).strip()


def parse_ticker(row: dict) -> Ticker:
    if not isinstance(row, dict):
        raise LedgerError("each ledger row must be a mapping")
    symbol = _require_str(row, "symbol", "?")
    thesis = " ".join(str(row.get("thesis") or "").split())
    if not thesis:
        raise LedgerError(f"{symbol}: no thesis — will not watch")
    raw_kpis = row.get("kpis")
    if not raw_kpis or not isinstance(raw_kpis, list):
        raise LedgerError(f"{symbol}: no KPI — will not watch")
    kpis: list[Kpi] = []
    for i, item in enumerate(raw_kpis):
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            raise LedgerError(f"{symbol}: kpis[{i}] needs a name")
        kpis.append(
            Kpi(
                name=str(item["name"]).strip(),
                label=str(item.get("label") or item["name"]).strip(),
                check=str(item.get("check") or "").strip(),
            )
        )
    status = str(row.get("status") or "held").strip().lower()
    if status not in VALID_STATUS:
        raise LedgerError(f"{symbol}: status must be held or watchlist")
    bse_code = str(row.get("bse_code") or "").strip()
    if not bse_code:
        raise LedgerError(f"{symbol}: missing bse_code")
    nse = row.get("nse_symbol")
    try:
        qty = float(row.get("qty") or 0)
        avg_cost = float(row.get("avg_cost") or 0)
        confidence = int(row.get("confidence") or 0)
    except (TypeError, ValueError) as exc:
        raise LedgerError(f"{symbol}: qty/avg_cost/confidence must be numeric") from exc
    if not 0 <= confidence <= 100:
        raise LedgerError(f"{symbol}: confidence must be 0–100")
    return Ticker(
        symbol=symbol.upper(),
        bse_code=bse_code,
        nse_symbol=str(nse).strip().upper() if nse else None,
        status=status,
        sector=str(row["sector"]).strip() if row.get("sector") else None,
        qty=qty,
        avg_cost=avg_cost,
        confidence=confidence,
        review_by=_as_date(row.get("review_by"), "review_by", symbol),
        thesis=thesis,
        kpis=tuple(kpis),
        results_due=_as_date(row.get("results_due"), "results_due", symbol),
        isin=str(row.get("isin") or "").strip().upper(),
    )


def load_tickers(path: Path | None = None) -> list[Ticker]:
    target = path or TICKERS_PATH
    if not target.exists():
        raise LedgerError(
            f"Missing {target}. Copy {TICKERS_EXAMPLE_PATH} to {TICKERS_PATH} "
            "and fill real theses + KPIs."
        )
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise LedgerError(f"{target}: expected a non-empty list of names")
    tickers = [parse_ticker(row) for row in raw]
    seen: set[str] = set()
    for t in tickers:
        if t.symbol in seen:
            raise LedgerError(f"duplicate symbol {t.symbol}")
        seen.add(t.symbol)
    return tickers


def by_symbol(tickers: list[Ticker], symbol: str) -> Ticker:
    key = symbol.strip().upper()
    for t in tickers:
        if t.symbol == key or t.bse_code == symbol.strip():
            return t
    raise LedgerError(f"{symbol} is not in the ledger")


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    path = Path(args[0]) if args else None
    try:
        tickers = load_tickers(path)
    except LedgerError as exc:
        print(f"ledger: {exc}", file=sys.stderr)
        return 1
    for t in tickers:
        kpi_names = ", ".join(k.name for k in t.kpis)
        print(f"{t.symbol}\t{t.status}\tbse={t.bse_code}\tkpis={kpi_names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
