from pathlib import Path

import pytest
import yaml

from src.ledger import LedgerError, load_tickers, parse_ticker


def test_example_ledger_loads():
    tickers = load_tickers(Path("config/tickers.example.yaml"))
    assert tickers[0].symbol == "SUZLON"
    assert tickers[0].kpis


def test_refuse_no_thesis(tmp_path: Path):
    path = tmp_path / "tickers.yaml"
    path.write_text(
        yaml.dump(
            [
                {
                    "symbol": "FOO",
                    "bse_code": "1",
                    "thesis": "   ",
                    "kpis": [{"name": "rev"}],
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(LedgerError, match="no thesis"):
        load_tickers(path)


def test_refuse_no_kpi():
    with pytest.raises(LedgerError, match="no KPI"):
        parse_ticker({"symbol": "FOO", "bse_code": "1", "thesis": "why we own it", "kpis": []})
