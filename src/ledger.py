from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import yaml

from src.paths import SHARED_CONDITIONS_PATH, TICKERS_EXAMPLE_PATH, TICKERS_PATH

VALID_STATUS = {"held", "exiting", "event", "no_thesis", "manual"}
POLL_STATUSES = {"held", "exiting"}
SCORE_STATUSES = {"held"}
CHECK_TYPES = {"quantitative", "manual"}


class LedgerError(ValueError):
    """Invalid tickers.yaml — refuse to watch."""


@dataclass(frozen=True)
class Condition:
    text: str
    check: str
    kpi: str | None = None
    threshold: str | None = None
    source: str | None = None


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
    conditions: tuple[Condition, ...] = ()
    results_due: date | None = None
    isin: str = ""

    def thesis_short(self, width: int = 48) -> str:
        line = " ".join(self.thesis.split())
        if not line:
            return "—"
        if len(line) <= width:
            return line
        return line[: width - 1] + "…"

    def polls(self) -> bool:
        return self.status in POLL_STATUSES

    def scores(self) -> bool:
        return self.status in SCORE_STATUSES

    def quantitative_names(self) -> frozenset[str]:
        names = {
            c.kpi
            for c in self.conditions
            if c.check == "quantitative" and c.kpi
        }
        if not self.conditions:
            names |= {k.name for k in self.kpis}
        return frozenset(n for n in names if n)


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


def _fold_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def names_match(left: str, right: str) -> bool:
    return _fold_name(left) == _fold_name(right)


def load_shared_conditions(path: Path | None = None) -> dict[str, list]:
    target = path or SHARED_CONDITIONS_PATH
    if not target.exists():
        return {}
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise LedgerError(f"{target}: expected a mapping of named condition blocks")
    blocks: dict[str, list] = {}
    for key, items in raw.items():
        name = str(key).strip()
        if not name:
            continue
        if not isinstance(items, list):
            raise LedgerError(f"{target}: {name} must be a list")
        blocks[name] = items
    return blocks


def parse_condition(item: object, symbol: str, *, source: str | None = None) -> Condition:
    if isinstance(item, str):
        text = " ".join(item.split())
        if not text:
            raise LedgerError(f"{symbol}: empty condition")
        return Condition(text=text, check="manual", source=source)
    if not isinstance(item, dict):
        raise LedgerError(f"{symbol}: condition must be text or a mapping")
    check = str(item.get("check") or "").strip().lower()
    text = " ".join(str(item.get("text") or item.get("label") or "").split())
    kpi = str(item.get("kpi") or "").strip() or None
    threshold = str(item.get("threshold") or "").strip() or None
    if not check and item.get("name"):
        kpi = str(item["name"]).strip()
        if not text:
            text = str(item.get("label") or kpi).strip()
        return Condition(
            text=text,
            check="quantitative",
            kpi=kpi,
            threshold=str(item.get("check") or item.get("threshold") or "").strip() or None,
            source=source,
        )
    if check not in CHECK_TYPES:
        raise LedgerError(f"{symbol}: condition check must be quantitative or manual")
    if check == "quantitative":
        if not kpi:
            kpi = str(item.get("name") or "").strip() or None
        if not kpi:
            raise LedgerError(f"{symbol}: quantitative condition needs kpi")
        if not text:
            text = kpi
        return Condition(
            text=text,
            check="quantitative",
            kpi=kpi,
            threshold=threshold,
            source=source,
        )
    if not text:
        raise LedgerError(f"{symbol}: manual condition needs text")
    return Condition(text=text, check="manual", kpi=kpi, threshold=threshold, source=source)


def _kpis_from_conditions(conditions: tuple[Condition, ...]) -> tuple[Kpi, ...]:
    kpis: list[Kpi] = []
    seen: set[str] = set()
    for cond in conditions:
        if cond.check != "quantitative" or not cond.kpi:
            continue
        key = _fold_name(cond.kpi)
        if key in seen:
            continue
        seen.add(key)
        kpis.append(
            Kpi(
                name=cond.kpi,
                label=cond.text,
                check=cond.threshold or "quantitative",
            )
        )
    return tuple(kpis)


def _merge_conditions(
    row: dict,
    symbol: str,
    shared: dict[str, list],
) -> tuple[Condition, ...]:
    merged: list[Condition] = []
    seen: set[str] = set()

    def append(cond: Condition) -> None:
        key = cond.text.casefold()
        if key in seen:
            return
        seen.add(key)
        merged.append(cond)

    includes = row.get("conditions_include") or []
    if includes and not isinstance(includes, list):
        raise LedgerError(f"{symbol}: conditions_include must be a list")
    for name in includes:
        key = str(name).strip()
        if key not in shared:
            raise LedgerError(f"{symbol}: unknown conditions_include {key}")
        for item in shared[key]:
            append(parse_condition(item, symbol, source=key))

    raw_conditions = row.get("conditions") or []
    if raw_conditions and not isinstance(raw_conditions, list):
        raise LedgerError(f"{symbol}: conditions must be a list")
    for item in raw_conditions:
        append(parse_condition(item, symbol))

    raw_kpis = row.get("kpis") or []
    if raw_kpis and not isinstance(raw_kpis, list):
        raise LedgerError(f"{symbol}: kpis must be a list")
    for item in raw_kpis:
        append(parse_condition(item, symbol))

    return tuple(merged)


def parse_ticker(
    row: dict,
    *,
    shared: dict[str, list] | None = None,
) -> Ticker:
    if not isinstance(row, dict):
        raise LedgerError("each ledger row must be a mapping")
    symbol = _require_str(row, "symbol", "?")
    status = str(row.get("status") or "held").strip().lower()
    if status not in VALID_STATUS:
        raise LedgerError(
            f"{symbol}: status must be held, exiting, event, no_thesis, or manual"
        )
    thesis = " ".join(str(row.get("thesis") or "").split())
    conditions = _merge_conditions(row, symbol, shared or {})
    if status == "held":
        if not thesis:
            raise LedgerError(f"{symbol}: no thesis — will not watch")
        if not conditions:
            raise LedgerError(f"{symbol}: no condition — will not watch")
    bse_code = str(row.get("bse_code") or "").strip()
    if status in {"held", "exiting"} and not bse_code:
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
    kpis = _kpis_from_conditions(conditions)
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
        kpis=kpis,
        conditions=conditions,
        results_due=_as_date(row.get("results_due"), "results_due", symbol),
        isin=str(row.get("isin") or "").strip().upper(),
    )


def load_tickers(
    path: Path | None = None,
    *,
    shared_path: Path | None = None,
) -> list[Ticker]:
    target = path or TICKERS_PATH
    if not target.exists():
        raise LedgerError(
            f"Missing {target}. Copy {TICKERS_EXAMPLE_PATH} to {TICKERS_PATH} "
            "and fill real theses + conditions."
        )
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise LedgerError(f"{target}: expected a non-empty list of names")
    shared = load_shared_conditions(shared_path)
    tickers = [parse_ticker(row, shared=shared) for row in raw]
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
        n_q = sum(1 for c in t.conditions if c.check == "quantitative")
        n_m = sum(1 for c in t.conditions if c.check == "manual")
        print(
            f"{t.symbol}\t{t.status}\tbse={t.bse_code or '—'}\t"
            f"conditions={n_q}q/{n_m}m"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
