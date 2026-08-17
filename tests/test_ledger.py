from pathlib import Path

import pytest
import yaml

from src.ledger import LedgerError, load_tickers, parse_ticker


def test_example_ledger_loads():
    tickers = load_tickers(Path("config/tickers.example.yaml"))
    assert tickers[0].symbol == "SUZLON"
    assert tickers[0].status == "held"
    assert tickers[0].kpis
    names = {c.text for c in tickers[0].conditions}
    assert any(c.check == "quantitative" for c in tickers[0].conditions)
    assert "CFO departs" in names
    assert "Moat erodes, story stops making sense" in names
    assert {c.severity for c in tickers[0].conditions} <= {"structural", "material", "watch"}


def test_refuse_no_thesis(tmp_path: Path):
    path = tmp_path / "tickers.yaml"
    path.write_text(
        yaml.dump(
            {
                "tickers": [
                    {
                        "symbol": "FOO",
                        "bse_code": "1",
                        "thesis": "   ",
                        "kpis": [{"name": "rev", "severity": "material"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(LedgerError, match="no thesis"):
        load_tickers(path)


def test_refuse_no_condition():
    with pytest.raises(LedgerError, match="no condition"):
        parse_ticker({"symbol": "FOO", "bse_code": "1", "thesis": "why we own it"})


def test_unspecified_status_defaults_to_held_and_fails_without_thesis():
    with pytest.raises(LedgerError, match="no thesis"):
        parse_ticker({"symbol": "FOO", "bse_code": "1"})


def test_invalid_status_rejected():
    with pytest.raises(LedgerError, match="status must be"):
        parse_ticker(
            {
                "symbol": "FOO",
                "bse_code": "1",
                "status": "watchlist",
                "thesis": "why",
                "kpis": [{"name": "rev", "severity": "material"}],
            }
        )


def test_exiting_loads_without_conditions():
    t = parse_ticker({"symbol": "FOO", "bse_code": "1", "status": "exiting"})
    assert t.status == "exiting"
    assert t.conditions == ()
    assert t.polls() is True
    assert t.scores() is False


def test_event_loads_without_conditions_or_bse():
    t = parse_ticker({"symbol": "FOO", "status": "event"})
    assert t.status == "event"
    assert t.polls() is False
    assert t.scores() is False


def test_no_thesis_loads_without_thesis_or_conditions():
    t = parse_ticker({"symbol": "FOO", "bse_code": "1", "status": "no_thesis"})
    assert t.status == "no_thesis"
    assert t.thesis == ""
    assert t.polls() is False


def test_manual_loads_without_conditions():
    t = parse_ticker({"symbol": "GOLDBEES", "status": "manual", "nse_symbol": "GOLDBEES"})
    assert t.status == "manual"
    assert t.polls() is False
    assert t.scores() is False


def test_held_without_bse_code_loads_but_does_not_poll():
    t = parse_ticker(
        {
            "symbol": "ANANTRAJ",
            "bse_code": "",
            "thesis": "data centre is the play",
            "conditions": [
                {
                    "text": "capacity stalls",
                    "check": "quantitative",
                    "kpi": "dc_capacity_mw",
                    "severity": "structural",
                }
            ],
        }
    )
    assert t.status == "held"
    assert t.polls() is False


def test_condition_without_severity_rejected():
    with pytest.raises(LedgerError, match="needs severity"):
        parse_ticker(
            {
                "symbol": "FOO",
                "bse_code": "1",
                "thesis": "why we own it",
                "conditions": [{"text": "Moat erodes", "check": "manual"}],
            }
        )


def test_quantitative_condition_requires_kpi():
    with pytest.raises(LedgerError, match="needs kpi"):
        parse_ticker(
            {
                "symbol": "FOO",
                "bse_code": "1",
                "thesis": "why we own it",
                "conditions": [
                    {"text": "growth stalls", "check": "quantitative", "severity": "material"}
                ],
            }
        )


def test_manual_condition_valid_without_kpi():
    t = parse_ticker(
        {
            "symbol": "FOO",
            "bse_code": "1",
            "thesis": "why we own it",
            "conditions": [
                {
                    "text": "Moat erodes, story stops making sense",
                    "check": "manual",
                    "severity": "watch",
                }
            ],
        }
    )
    assert t.kpis == ()
    assert t.conditions[0].check == "manual"
    assert t.conditions[0].severity == "watch"
    assert t.quantitative_names() == frozenset()


def test_conditions_include_merges_with_entry_level(tmp_path: Path):
    ledger = tmp_path / "tickers.yaml"
    ledger.write_text(
        yaml.dump(
            {
                "shared_conditions": {
                    "quality_default": [
                        {"text": "CFO departs", "check": "manual", "severity": "watch"},
                        {
                            "text": "Order inflow stops growing",
                            "check": "quantitative",
                            "kpi": "order_inflow_ttm",
                            "severity": "material",
                        },
                    ]
                },
                "tickers": [
                    {
                        "symbol": "FOO",
                        "bse_code": "1",
                        "thesis": "why we own it",
                        "conditions_include": ["quality_default"],
                        "conditions": [
                            {
                                "text": "Moat erodes, story stops making sense",
                                "check": "manual",
                                "severity": "watch",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    tickers = load_tickers(ledger)
    texts = [c.text for c in tickers[0].conditions]
    assert texts[0] == "CFO departs"
    assert "Order inflow stops growing" in texts
    assert texts[-1] == "Moat erodes, story stops making sense"
    assert {c.check for c in tickers[0].conditions} == {"manual", "quantitative"}
    assert tickers[0].kpis[0].name == "order_inflow_ttm"
    assert tickers[0].conditions[0].source == "quality_default"
