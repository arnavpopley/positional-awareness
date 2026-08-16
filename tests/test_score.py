from __future__ import annotations

import ast
import re
from pathlib import Path

from src.score import WEIGHTS, active, band_for, naive_weighted_sum, persist, score
from src.store import Store

FORBIDDEN = ("add", "trim", "buy", "sell")


def test_order_win_only_reaches_strongly_positive_band():
    result = score(book=active(1.0, raw=1.0))
    assert result.S == 1.0
    assert result.S >= 0.60
    assert band_for(result.S) == "strongly positive"
    assert result.active_factors == ("book",)


def test_zero_active_factors_undefined():
    result = score()
    assert result.S is None
    assert result.band is None
    assert result.active_factors == ()
    assert all(line.endswith("n/a") for line in result.lines)


def test_single_active_factor_low_confidence_suppresses_band():
    result = score(book=active(1.0))
    assert result.low_confidence is True
    assert result.band is None
    assert "n/a" in result.display()
    assert "0.00" not in "".join(line for line in result.lines if line.endswith("n/a"))


def test_all_five_active_matches_naive_sum():
    xs = dict(kpi=0.4, book=-0.2, industry=0.0, price=0.8, guidance=-1.0)
    result = score(
        kpi=active(xs["kpi"]),
        book=active(xs["book"]),
        industry=active(xs["industry"]),
        price=active(xs["price"]),
        guidance=active(xs["guidance"]),
    )
    naive = naive_weighted_sum(**xs)
    assert result.S == naive
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-12
    assert result.low_confidence is False
    assert result.band == band_for(naive)
    assert result.active_factors == ("kpi", "book", "industry", "price", "guidance")


def test_inactive_lines_are_na_not_zero():
    result = score(book=active(0.5), price=active(-0.5))
    na_lines = [line for line in result.lines if ": n/a" in line]
    assert len(na_lines) == 3
    for line in result.lines:
        if not line.endswith("n/a"):
            continue
        assert "0.00" not in line
        assert "0.0" not in line


def test_persist_active_factors(tmp_path: Path):
    store = Store(tmp_path / "pa.sqlite")
    result = score(book=active(1.0), price=active(0.2))
    row_id = persist(result, store, filing_id=None)
    row = store.conn.execute("SELECT * FROM scores WHERE id = ?", (row_id,)).fetchone()
    assert row["active_factors"] == "book,price"
    assert row["S"] == result.S
    assert row["low_confidence"] == 0
    store.close()


def test_no_action_verbs_in_src_output_strings():
    verb = re.compile(r"\b(" + "|".join(FORBIDDEN) + r")\b", re.I)
    hits: list[str] = []
    for path in Path("src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value
                if "CREATE TABLE" in text or "ALTER TABLE" in text:
                    continue
                if verb.search(text):
                    hits.append(f"{path}:{node.lineno}:{text!r}")
    assert hits == []
