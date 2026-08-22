from __future__ import annotations

import hashlib
import os
import sys
import time

import requests
from dotenv import load_dotenv

from src.ledger import Ticker
from src.paths import ROOT
from src.portfolio.base import Holding, Portfolio

HOLDINGS_URL = "https://api.groww.in/v1/holdings/user"
LTP_URL = "https://api.groww.in/v1/live-data/ltp"
TOKEN_URL = "https://api.groww.in/v1/token/api/access"


class GrowwError(RuntimeError):
    """Holdings request failed. Message must never contain credentials."""


class _RedactedBearer(requests.auth.AuthBase):
    def __init__(self, token: str) -> None:
        self._token = token

    def __call__(self, request: requests.PreparedRequest) -> requests.PreparedRequest:
        request.headers["Authorization"] = f"Bearer {self._token}"
        return request

    def __repr__(self) -> str:
        return "<redacted>"


def _redact(text: str, *secrets: str) -> str:
    for secret in secrets:
        if secret and secret in text:
            text = text.replace(secret, "<redacted>")
    return text


def checksum(secret: str, timestamp: str) -> str:
    """SHA-256 of api_secret + epoch-seconds, as specified by Groww."""
    return hashlib.sha256(f"{secret}{timestamp}".encode("utf-8")).hexdigest()


def _parse_access_token(payload: object) -> str:
    if not isinstance(payload, dict):
        raise GrowwError("Groww token request failed")
    token = payload.get("token")
    if isinstance(token, str) and token.strip():
        return token.strip()
    inner = payload.get("payload")
    if isinstance(inner, dict):
        nested = inner.get("token")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    raise GrowwError("Groww token request failed")


class GrowwPortfolio(Portfolio):
    """Read-only holdings. API key + secret in .env; no growwapi SDK."""

    def __init__(
        self,
        token: str | None = None,
        *,
        api_key: str | None = None,
        api_secret: str | None = None,
        session: requests.Session | None = None,
        timestamp: str | None = None,
    ) -> None:
        if api_key is None or api_secret is None or token is None:
            load_dotenv(ROOT / ".env")
        if api_key is None:
            api_key = os.environ.get("GROWW_API_KEY") or ""
        if api_secret is None:
            api_secret = os.environ.get("GROWW_API_SECRET") or ""
        if token is None:
            token = os.environ.get("GROWW_ACCESS_TOKEN") or ""
        self._api_key = api_key
        self._api_secret = api_secret
        self._token = token
        self._timestamp = timestamp
        self._session = session or requests.Session()
        self._access = ""

    def _secrets(self, *extra: str) -> tuple[str, ...]:
        return (self._api_key, self._api_secret, self._token, *extra)

    def _exchange_access_token(self) -> str:
        ts = self._timestamp or str(int(time.time()))
        body = {
            "key_type": "approval",
            "checksum": checksum(self._api_secret, ts),
            "timestamp": ts,
        }
        try:
            response = self._session.post(
                TOKEN_URL,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-API-VERSION": "1.0",
                },
                json=body,
                auth=_RedactedBearer(self._api_key),
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise GrowwError(
                _redact(f"Groww token request failed: {exc}", *self._secrets())
            ) from None
        except ValueError:
            raise GrowwError("Groww token request failed") from None
        if str(payload.get("status") or "").upper() == "FAILURE":
            raise GrowwError("Groww token request failed")
        return _parse_access_token(payload)

    def _access_token(self) -> str:
        if self._access:
            return self._access
        if self._api_key and self._api_secret:
            self._access = self._exchange_access_token()
            return self._access
        if self._token:
            self._access = self._token
            return self._access
        raise GrowwError("GROWW_API_KEY and GROWW_API_SECRET are missing")

    def fetch(self) -> list[Holding]:
        access = self._access_token()
        try:
            response = self._session.get(
                HOLDINGS_URL,
                headers={
                    "Accept": "application/json",
                    "X-API-VERSION": "1.0",
                },
                auth=_RedactedBearer(access),
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise GrowwError(
                _redact(
                    f"Groww holdings request failed: {exc}",
                    *self._secrets(access),
                )
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

    def ltp_map(self, tickers: list[Ticker]) -> dict[str, float]:
        """Groww CMP keyed by ledger symbol. Read-only. Never places a trade."""
        keys: list[str] = []
        seen: set[str] = set()
        for ticker in tickers:
            for key in _cash_keys(ticker):
                if key not in seen:
                    seen.add(key)
                    keys.append(key)
        if not keys:
            return {}
        access = self._access_token()
        try:
            response = self._session.get(
                LTP_URL,
                params={"segment": "CASH", "exchange_symbols": ",".join(keys)},
                headers={
                    "Accept": "application/json",
                    "X-API-VERSION": "1.0",
                },
                auth=_RedactedBearer(access),
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise GrowwError(
                _redact(
                    f"Groww LTP request failed: {exc}",
                    *self._secrets(access),
                )
            ) from None
        except ValueError:
            raise GrowwError("Groww LTP request failed") from None
        if str(payload.get("status") or "").upper() != "SUCCESS":
            raise GrowwError("Groww LTP request failed")
        raw = payload.get("payload") or {}
        if not isinstance(raw, dict):
            raise GrowwError("Groww LTP request failed")
        out: dict[str, float] = {}
        for ticker in tickers:
            for key in _cash_keys(ticker):
                price = _as_price(raw.get(key))
                if price is None:
                    continue
                out[ticker.symbol] = price
                break
        return out


def _cash_keys(ticker: Ticker) -> tuple[str, ...]:
    nse = (ticker.nse_symbol or ticker.symbol).strip().upper()
    return (f"NSE_{nse}", f"BSE_{nse}")


def _as_price(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    del argv
    print("Groww holdings fetch is only via: pos sync", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
