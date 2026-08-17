from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, replace

from src.ledger import Ticker

# Frozen beta weights (SPEC.md §3). Do not retune.
WEIGHTS: dict[str, float] = {
    "kpi": 0.40,
    "book": 0.20,
    "industry": 0.15,
    "price": 0.15,
    "guidance": 0.10,
}
FACTOR_ORDER = ("kpi", "book", "industry", "price", "guidance")
KPI_CAP = 0.25
PRICE_CAP = 0.15
_BOOK_NAME = re.compile(r"order|book", re.I)


@dataclass(frozen=True)
class Factor:
    """One scorecard factor. Inactive is not the same as x = 0."""

    value: float
    active: bool
    raw: float | None = None

    def __post_init__(self) -> None:
        if self.active:
            clamped = max(-1.0, min(1.0, float(self.value)))
            object.__setattr__(self, "value", clamped)


def inactive() -> Factor:
    return Factor(value=0.0, active=False, raw=None)


def active(value: float, *, raw: float | None = None) -> Factor:
    return Factor(value=value, active=True, raw=value if raw is None else raw)


def band_for(s: float) -> str:
    if s >= 0.60:
        return "strongly positive"
    if s >= 0.25:
        return "positive"
    if s > -0.25:
        return "neutral"
    if s > -0.60:
        return "negative"
    return "strongly negative"


def _fmt_signed(value: float, digits: int = 2) -> str:
    return f"{value:+.{digits}f}"


def _line(name: str, factor: Factor, weight: float) -> str:
    if not factor.active:
        return f"{name}: n/a"
    raw = factor.raw if factor.raw is not None else factor.value
    contrib = weight * factor.value
    return (
        f"{name}: raw={_fmt_signed(raw, 3)} → x={_fmt_signed(factor.value)} "
        f"→ w·x={_fmt_signed(contrib, 3)}"
    )


@dataclass(frozen=True)
class ScoreResult:
    S: float | None
    band: str | None
    low_confidence: bool
    active_factors: tuple[str, ...]
    lines: tuple[str, ...]
    x: dict[str, float | None]

    def display(self) -> str:
        body = "\n".join(self.lines)
        if self.S is None:
            return f"{body}\nS=undefined (no active factors)"
        extra = f"S={_fmt_signed(self.S)}"
        if self.band:
            extra += f"  {self.band}"
        if self.low_confidence:
            extra += "  low_confidence"
        return f"{body}\n{extra}"


def score(
    *,
    kpi: Factor | None = None,
    book: Factor | None = None,
    industry: Factor | None = None,
    price: Factor | None = None,
    guidance: Factor | None = None,
) -> ScoreResult:
    """Renormalised S over active factors only."""
    factors = {
        "kpi": kpi if kpi is not None else inactive(),
        "book": book if book is not None else inactive(),
        "industry": industry if industry is not None else inactive(),
        "price": price if price is not None else inactive(),
        "guidance": guidance if guidance is not None else inactive(),
    }
    active_names = tuple(name for name in FACTOR_ORDER if factors[name].active)
    lines = tuple(_line(name, factors[name], WEIGHTS[name]) for name in FACTOR_ORDER)
    x = {name: (factors[name].value if factors[name].active else None) for name in FACTOR_ORDER}

    if not active_names:
        return ScoreResult(
            S=None,
            band=None,
            low_confidence=True,
            active_factors=(),
            lines=lines,
            x=x,
        )

    w_sum = sum(WEIGHTS[name] for name in active_names)
    s = sum(WEIGHTS[name] * factors[name].value for name in active_names) / w_sum
    low_confidence = len(active_names) < 2
    band = None if low_confidence else band_for(s)
    return ScoreResult(
        S=s,
        band=band,
        low_confidence=low_confidence,
        active_factors=active_names,
        lines=lines,
        x=x,
    )


def naive_weighted_sum(
    *,
    kpi: float,
    book: float,
    industry: float,
    price: float,
    guidance: float,
) -> float:
    return (
        WEIGHTS["kpi"] * kpi
        + WEIGHTS["book"] * book
        + WEIGHTS["industry"] * industry
        + WEIGHTS["price"] * price
        + WEIGHTS["guidance"] * guidance
    )


def persist(
    result: ScoreResult,
    store: object,
    filing_id: int | None = None,
    *,
    triage: dict | None = None,
) -> int:
    """Write S and active_factors."""
    return store.insert_score(  # type: ignore[attr-defined]
        filing_id=filing_id,
        x_kpi=result.x["kpi"],
        x_book=result.x["book"],
        x_industry=result.x["industry"],
        x_price=result.x["price"],
        x_guidance=result.x["guidance"],
        S=result.S,
        band=result.band,
        low_confidence=result.low_confidence,
        active_factors=result.active_factors,
        triage_json=json.dumps(triage, ensure_ascii=False) if triage else None,
    )


def x_from_pct(raw: float, cap: float) -> float:
    clipped = max(-cap, min(cap, raw))
    return clipped / cap


def _qoq(value: object, prior: object) -> float | None:
    if value is None or prior is None:
        return None
    try:
        current = float(value)
        base = float(prior)
    except (TypeError, ValueError):
        return None
    if base == 0:
        return None
    return (current - base) / abs(base)


def _is_book_kpi(name: str) -> bool:
    return bool(_BOOK_NAME.search(name or ""))


def _kpi_rows(payload: dict | None) -> list[dict]:
    if not payload:
        return []
    rows = payload.get("kpis") or []
    return [row for row in rows if isinstance(row, dict)]


def kpi_factor(payload: dict | None) -> Factor:
    xs: list[float] = []
    raws: list[float] = []
    for row in _kpi_rows(payload):
        if not row.get("found"):
            continue
        name = str(row.get("name") or "")
        if _is_book_kpi(name):
            continue
        raw = _qoq(row.get("value"), row.get("prior_value"))
        if raw is None:
            continue
        raws.append(raw)
        xs.append(x_from_pct(raw, KPI_CAP))
    if not xs:
        return inactive()
    return active(sum(xs) / len(xs), raw=sum(raws) / len(raws))


def book_factor(payload: dict | None) -> Factor:
    if not payload:
        return inactive()
    order = payload.get("order") if isinstance(payload.get("order"), dict) else {}
    if order.get("found") and order.get("value") is not None:
        q_sales = order.get("q_sales") or order.get("quarterly_sales")
        try:
            amount = float(order["value"])
        except (TypeError, ValueError):
            amount = None
        if amount is not None and q_sales not in (None, ""):
            try:
                sales = float(q_sales)
            except (TypeError, ValueError):
                sales = 0.0
            if sales > 0:
                raw = amount / sales
                x = math.copysign(min(1.0, abs(raw)), raw)
                return active(x, raw=raw)
    xs: list[float] = []
    raws: list[float] = []
    for row in _kpi_rows(payload):
        if not row.get("found"):
            continue
        name = str(row.get("name") or "")
        if not _is_book_kpi(name):
            continue
        raw = _qoq(row.get("value"), row.get("prior_value"))
        if raw is None:
            continue
        raws.append(raw)
        xs.append(x_from_pct(raw, KPI_CAP))
    if not xs:
        return inactive()
    return active(sum(xs) / len(xs), raw=sum(raws) / len(raws))


def guidance_factor(payload: dict | None) -> Factor:
    if not payload:
        return inactive()
    g = payload.get("guidance") if isinstance(payload.get("guidance"), dict) else {}
    if not g.get("touches_named_kpi"):
        return inactive()
    try:
        direction = int(g.get("direction"))
    except (TypeError, ValueError):
        return inactive()
    if direction not in (-1, 0, 1):
        return inactive()
    return active(float(direction), raw=float(direction))


def price_factor(return_20d: float | None) -> Factor:
    if return_20d is None:
        return inactive()
    return active(x_from_pct(return_20d, PRICE_CAP), raw=return_20d)


def industry_factor(
    ticker: Ticker | None,
    peers: list[Ticker] | None,
    store: object | None,
) -> Factor:
    if ticker is None or not ticker.sector or store is None or not peers:
        return inactive()
    zs: list[float] = []
    for peer in peers:
        if peer.symbol == ticker.symbol or peer.sector != ticker.sector:
            continue
        history = store.kpi_qoq_history(peer.symbol)  # type: ignore[attr-defined]
        if len(history) < 3:
            continue
        mean = sum(history) / len(history)
        var = sum((x - mean) ** 2 for x in history) / len(history)
        std = math.sqrt(var)
        if std == 0:
            continue
        zs.append(max(-1.0, min(1.0, (history[-1] - mean) / std)))
    if not zs:
        return inactive()
    raw = sum(zs) / len(zs)
    return active(max(-1.0, min(1.0, raw)), raw=raw)


def record_kpi_prints(
    payload: dict | None,
    ticker: Ticker | None,
    store: object | None,
    filing_id: int | None,
) -> None:
    if not payload or ticker is None or store is None:
        return
    for row in _kpi_rows(payload):
        if not row.get("found") or row.get("value") is None:
            continue
        period = str(row.get("period") or "").strip()
        name = str(row.get("name") or "").strip()
        if not name or not period:
            continue
        try:
            value = float(row["value"])
        except (TypeError, ValueError):
            continue
        store.insert_kpi_print(  # type: ignore[attr-defined]
            ticker=ticker.symbol,
            kpi_name=name,
            period=period,
            value=value,
            source_filing_id=filing_id,
        )


def score_extraction(
    payload: dict | None,
    *,
    ticker: Ticker | None = None,
    peers: list[Ticker] | None = None,
    store: object | None = None,
    price_return_20d: float | None = None,
    needs_manual_read: bool = False,
    filing_id: int | None = None,
) -> ScoreResult:
    """Deterministic S from Gemini JSON. Gemini is not called here."""
    record_kpi_prints(payload, ticker, store, filing_id)
    result = score(
        kpi=kpi_factor(payload),
        book=book_factor(payload),
        industry=industry_factor(ticker, peers, store),
        price=price_factor(price_return_20d),
        guidance=guidance_factor(payload),
    )
    if needs_manual_read:
        result = replace(result, band=None)
    return result


def main(argv: list[str] | None = None) -> int:
    del argv
    demo = score(book=active(1.0, raw=1.0))
    print(demo.display())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
