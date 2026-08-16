from __future__ import annotations

from dataclasses import dataclass

# Frozen beta weights (SPEC.md §3). Do not retune.
WEIGHTS: dict[str, float] = {
    "kpi": 0.40,
    "book": 0.20,
    "industry": 0.15,
    "price": 0.15,
    "guidance": 0.10,
}
FACTOR_ORDER = ("kpi", "book", "industry", "price", "guidance")


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
    """Renormalised S over active factors only. Not wired to filings."""
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


def persist(result: ScoreResult, store: object, filing_id: int | None = None) -> int:
    """Write S and active_factors. Caller is tests / Phase 1; ingest does not call this."""
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
    )


def main(argv: list[str] | None = None) -> int:
    del argv
    demo = score(book=active(1.0, raw=1.0))
    print(demo.display())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
