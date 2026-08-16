from __future__ import annotations

import os
import sys

import requests
from dotenv import load_dotenv

from src.paths import ROOT
from src.portfolio.base import Holding, Portfolio

HOLDINGS_URL = "https://api.groww.in/v1/holdings/user"


class GrowwError(RuntimeError):
    """Holdings request failed. Message must never contain the access token."""


class _RedactedBearer(requests.auth.AuthBase):
    def __init__(self, token: str) -> None:
        self._token = token

    def __call__(self, request: requests.PreparedRequest) -> requests.PreparedRequest:
        request.headers["Authorization"] = f"Bearer {self._token}"
        return request

    def __repr__(self) -> str:
        return "<redacted>"


def _redact(text: str, token: str) -> str:
    if token and token in text:
        return text.replace(token, "<redacted>")
    return text


class GrowwPortfolio(Portfolio):
    """Read-only holdings endpoint. Do not import growwapi; no order surface."""

    def __init__(
        self,
        token: str | None = None,
        *,
        session: requests.Session | None = None,
    ) -> None:
        if token is None:
            load_dotenv(ROOT / ".env")
            token = os.environ.get("GROWW_ACCESS_TOKEN") or ""
        self._token = token
        self._session = session or requests.Session()

    def fetch(self) -> list[Holding]:
        if not self._token:
            raise GrowwError("GROWW_ACCESS_TOKEN is missing")
        try:
            response = self._session.get(
                HOLDINGS_URL,
                headers={
                    "Accept": "application/json",
                    "X-API-VERSION": "1.0",
                },
                auth=_RedactedBearer(self._token),
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise GrowwError(
                _redact(f"Groww holdings request failed: {exc}", self._token)
            ) from None
        except ValueError:
            raise GrowwError("Groww holdings request failed") from None

        if str(payload.get("status") or "").upper() != "SUCCESS":
            raise GrowwError("Groww holdings request failed")
        rows = ((payload.get("payload") or {}).get("holdings")) or []
        holdings: list[Holding] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("trading_symbol") or "").strip().upper()
            if not symbol:
                continue
            holdings.append(
                Holding(
                    symbol=symbol,
                    isin=str(row.get("isin") or "").strip(),
                    qty=float(row.get("quantity") or 0),
                    avg_cost=float(row.get("average_price") or 0),
                )
            )
        return holdings


def main(argv: list[str] | None = None) -> int:
    del argv
    print("Groww holdings fetch is only via: pos sync", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
