from __future__ import annotations

import pytest
import requests


@pytest.fixture(autouse=True)
def _no_live_groww(monkeypatch: pytest.MonkeyPatch) -> None:
    orig = requests.Session.request

    def wrapped(self, method, url, *args, **kwargs):
        if "groww.in" in str(url).lower():
            raise RuntimeError("tests must not hit the live Groww API")
        return orig(self, method, url, *args, **kwargs)

    monkeypatch.setattr(requests.Session, "request", wrapped)
