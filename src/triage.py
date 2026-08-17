from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from src.ledger import Ticker
from src.store import Store

# Two quarters. Touches older than this drop out of the window.
WINDOW = timedelta(days=182)
LEVEL_RECORD = "record"
LEVEL_REVIEW = "review"
LEVEL_PRIORITY = "priority_review"


@dataclass(frozen=True)
class Escalation:
    level: str
    structural: int
    material: int
    watch: int
    texts: tuple[str, ...]

    def should_notify(self) -> bool:
        return self.level in {LEVEL_REVIEW, LEVEL_PRIORITY}


def _as_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value


def _count_unique(rows: list) -> tuple[int, int, int, tuple[str, ...]]:
    latest: dict[str, object] = {}
    for row in rows:
        latest[str(row["condition_text"])] = row
    n_struct = n_mat = n_watch = 0
    texts: list[str] = []
    for text, row in latest.items():
        texts.append(text)
        sev = str(row["severity"])
        if sev == "structural":
            n_struct += 1
        elif sev == "material":
            n_mat += 1
        elif sev == "watch":
            n_watch += 1
    return n_struct, n_mat, n_watch, tuple(texts)


def level_for(*, structural: int, material: int, watch: int) -> str:
    del watch
    if structural >= 1 and material >= 1:
        return LEVEL_PRIORITY
    if material >= 3:
        return LEVEL_PRIORITY
    if structural >= 1:
        return LEVEL_REVIEW
    if material >= 2:
        return LEVEL_REVIEW
    return LEVEL_RECORD


def escalate(
    ticker: Ticker,
    store: Store,
    *,
    as_of: date | datetime,
) -> Escalation:
    """Collective-thesis window. Never returns an action verb."""
    end = _as_date(as_of)
    start = end - WINDOW
    rows = store.touches_in_window(ticker.symbol, since=start, until=end)
    n_struct, n_mat, n_watch, texts = _count_unique(rows)
    return Escalation(
        level=level_for(structural=n_struct, material=n_mat, watch=n_watch),
        structural=n_struct,
        material=n_mat,
        watch=n_watch,
        texts=texts,
    )


def main(argv: list[str] | None = None) -> int:
    del argv
    print("escalate(ticker, store) -> record | review | priority_review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
