from __future__ import annotations

from pathlib import Path

from src.ledger import parse_ticker
from src.store import Store
from src.web.publish import HOST, publish
from tests.helpers import filing


def _held():
    return parse_ticker(
        {
            "symbol": "SUZLON",
            "bse_code": "532667",
            "thesis": "Two sentences. Why this position exists.",
            "conditions": [
                {
                    "text": "Order inflow stops growing",
                    "check": "quantitative",
                    "kpi": "order_inflow_ttm",
                    "severity": "material",
                }
            ],
        }
    )


def test_publish_writes_full_thesis_and_login(tmp_path: Path):
    db = tmp_path / "pa.sqlite"
    store = Store(db)
    store.insert_filing(
        filing(
            headline="Financial Results",
            category="Result",
            subcategory="Financial Results",
            ann_id="pub-1",
        ),
        "candidate",
    )
    dest = tmp_path / "site"
    publish(dest, tickers=[_held()], store=store, fetch_quotes=False)
    store.close()
    index = (dest / "index.html").read_text(encoding="utf-8")
    assert "Why this position exists." in index
    assert "pulse.js" not in index
    assert "hosted · delayed Groww" in index
    assert "CMP" in index
    assert "quotes.js" in index
    login = (dest / "login.html").read_text(encoding="utf-8")
    assert 'action="/api/login"' in login
    assert "PA_SITE_PASSWORD" not in index
    assert "PA_SITE_PASSWORD" not in login
    name = (dest / "t" / "SUZLON.html").read_text(encoding="utf-8")
    assert "Order inflow stops growing" in name
    assert "SUZLON" in (dest / "symbols.json").read_text(encoding="utf-8")


def test_stage_deploy_copies_gate(tmp_path: Path):
    import shutil

    store = Store(tmp_path / "pa.sqlite")
    site = publish(tmp_path / "snapshot", tickers=[_held()], store=store, fetch_quotes=False)
    store.close()
    dest = tmp_path / "stage"
    dest.mkdir()
    shutil.copy(HOST / "vercel.json", dest / "vercel.json")
    api = dest / "api"
    api.mkdir()
    shutil.copy(HOST / "api" / "gate.js", api / "gate.js")
    shutil.copy(site / "bundle.json", api / "bundle.json")
    bundle = (api / "bundle.json").read_text(encoding="utf-8")
    assert '"/"' in bundle
    assert "/t/SUZLON" in bundle
    assert (api / "gate.js").exists()


def test_publish_bakes_groww_cmp(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "src.web.publish.GrowwPortfolio.ltp_map",
        lambda self, tickers: {t.symbol: 50.25 for t in tickers},
    )
    ticker = parse_ticker(
        {
            "symbol": "SUZLON",
            "bse_code": "532667",
            "qty": 100,
            "avg_cost": 45.5,
            "thesis": "Two sentences. Why this position exists.",
            "conditions": [
                {
                    "text": "Order inflow stops growing",
                    "check": "quantitative",
                    "kpi": "order_inflow_ttm",
                    "severity": "material",
                }
            ],
        }
    )
    store = Store(tmp_path / "pa.sqlite")
    dest = tmp_path / "site"
    publish(dest, tickers=[ticker], store=store, fetch_quotes=True)
    store.close()
    index = (dest / "index.html").read_text(encoding="utf-8")
    name = (dest / "t" / "SUZLON.html").read_text(encoding="utf-8")
    assert "50.25" in index
    assert "+10.4%" in index
    assert "50.25" in name
    assert "+10.4%" in name
    assert "quotes.js" in index


def test_site_password_is_sixteen_chars():
    from src.web.deploy import ALPHABET, PASSWORD_LEN, new_password

    password = new_password()
    assert len(password) == 16
    assert PASSWORD_LEN == 16
    assert set(password) <= set(ALPHABET)


def test_deploy_refuses_new_url_when_logged_out(monkeypatch, capsys):
    from src.web.deploy import deploy

    monkeypatch.setattr("src.web.deploy._logged_in", lambda: False)

    def boom(*args, **kwargs):
        raise AssertionError("must not call vercel")

    monkeypatch.setattr("src.web.deploy.subprocess.run", boom)
    monkeypatch.setattr("src.web.deploy.stage_deploy", boom)
    assert deploy(fetch_quotes=False) == 2
    err = capsys.readouterr().out
    assert "Will not create a new URL" in err
    assert "--temporary" not in err


def test_repo_root_disables_git_autodeploy():
    import json
    from pathlib import Path

    from src.web.publish import HOST

    cfg = json.loads(Path("vercel.json").read_text(encoding="utf-8"))
    assert cfg["git"]["deploymentEnabled"] is False
    host = json.loads((HOST / "vercel.json").read_text(encoding="utf-8"))
    assert host["git"]["deploymentEnabled"] is False
