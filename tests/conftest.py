from __future__ import annotations

import pytest
import requests


@pytest.fixture(autouse=True)
def _no_live_groww_or_gemini(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    orig = requests.Session.request

    def wrapped(self, method, url, *args, **kwargs):
        lowered = str(url).lower()
        if "groww.in" in lowered or "generativelanguage.googleapis.com" in lowered:
            raise RuntimeError("tests must not hit live Groww or Gemini")
        return orig(self, method, url, *args, **kwargs)

    monkeypatch.setattr(requests.Session, "request", wrapped)
    if request.module.__name__.endswith("test_extract"):
        return
    monkeypatch.setattr(
        "src.extract.extract_filing",
        lambda *args, **kwargs: None,
        raising=False,
    )
