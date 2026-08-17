from __future__ import annotations

from pathlib import Path

from src.cli import decide_command, list_decisions_command
from src.ledger import parse_ticker
from src.store import Store


def _held():
    return parse_ticker(
        {
            "symbol": "SUZLON",
            "bse_code": "532667",
            "thesis": "Two sentences. Why this position exists.",
            "kpis": [{"name": "rev"}],
        }
    )


def test_anticipatory_flag_round_trips(tmp_path: Path, capsys):
    store = Store(tmp_path / "pa.sqlite")
    ticker = _held()
    assert (
        decide_command(
            "SUZLON",
            "pre_results",
            "before the print",
            anticipatory=True,
            store=store,
            tickers=[ticker],
        )
        == 0
    )
    assert (
        decide_command(
            "SUZLON",
            "after_print",
            "confirmed",
            anticipatory=False,
            store=store,
            tickers=[ticker],
        )
        == 0
    )
    rows = store.conn.execute(
        "SELECT action, anticipatory, note FROM decisions ORDER BY id"
    ).fetchall()
    assert rows[0]["action"] == "pre_results"
    assert rows[0]["anticipatory"] == 1
    assert rows[0]["note"] == "before the print"
    assert rows[1]["anticipatory"] == 0
    capsys.readouterr()
    assert list_decisions_command(anticipatory=True, store=store) == 0
    listed = capsys.readouterr().out
    assert "pre_results" in listed
    assert "after_print" not in listed
    store.close()
