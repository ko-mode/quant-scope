"""Tiingo adapter for daily price history - QuantScope's V1 live provider (ADR 0022).

Endpoint (JSON):
``GET {base}/tiingo/daily/{ticker}/prices?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&format=json``
with header ``Authorization: Token <token>``. The response is a JSON array of
objects::

    {"date": "2024-06-10T00:00:00.000Z",
     "open": 120.37, "high": 123.1, "low": 117.01, "close": 121.79, "volume": 308134266,
     "adjOpen": ..., "adjHigh": ..., "adjLow": ..., "adjClose": 121.79, "adjVolume": ...,
     "divCash": 0.0, "splitFactor": 1.0}

Field mapping into :class:`RawPriceBar` (values are stringified, ``None`` when
absent - never substituted for one another):

    date        -> trade_date   (date component only; the time/zone suffix is dropped)
    open        -> open
    high        -> high
    low         -> low
    close       -> close        (RAW as-traded close)
    adjClose    -> adj_close    (CRSP split + dividend adjusted; documented, see ADR 0022)
    volume      -> volume       (RAW volume; adjVolume is not used)

``divCash`` / ``splitFactor`` are not part of the ``RawPriceBar`` contract and
are dropped here; the dividend-adjustment spot-check (see
``quantscope.data.spot_checks``) works from the raw payload directly.

No Tiingo response is committed to the repository (ADR 0015); unit tests use
hand-authored synthetic JSON.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

import httpx

from quantscope.data.providers.base import (
    PriceDataUnavailableError,
    PriceProviderAuthError,
    PriceProviderConfigError,
    PriceProviderError,
    PriceProviderRateLimitedError,
    RawPriceBar,
)

logger = logging.getLogger(__name__)

SOURCE_NAME = "tiingo"
DEFAULT_BASE_URL = "https://api.tiingo.com"
_REQUEST_TIMEOUT = 30.0
_TOKEN_HELP = (
    "Set QUANTSCOPE_TIINGO_TOKEN to a Tiingo API token (free: sign up at "
    "https://www.tiingo.com and copy it from https://www.tiingo.com/account/api/token)."
)


def _to_str(value: Any) -> str | None:
    """Stringify a JSON scalar for :class:`RawPriceBar`; ``None`` stays ``None``."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return repr(value) if isinstance(value, float) else str(value)


def _date_part(value: Any) -> str | None:
    """``"2024-06-10T00:00:00.000Z"`` -> ``"2024-06-10"``; other shapes pass through."""
    if not isinstance(value, str):
        return _to_str(value)
    text = value.strip()
    if text == "":
        return None
    return text.split("T", 1)[0]


def parse_tiingo_eod(payload: object, source: str = SOURCE_NAME) -> list[RawPriceBar]:
    """Parse a Tiingo EOD ``/prices`` JSON document into raw bars (pure; no I/O).

    Raises :class:`PriceProviderError` for a structurally malformed document and
    :class:`PriceDataUnavailableError` for a well-formed but empty result.
    """
    if isinstance(payload, dict) and "detail" in payload:
        # Tiingo returns {"detail": "..."} for errors even with a 200 in some cases.
        raise PriceDataUnavailableError(f"{source}: {payload['detail']!r}")
    if not isinstance(payload, list):
        raise PriceProviderError(
            f"{source}: expected a JSON array of bars, got {type(payload).__name__}"
        )
    if not payload:
        raise PriceDataUnavailableError(f"{source}: empty result (no bars for ticker/range)")

    bars: list[RawPriceBar] = []
    for row in payload:
        if not isinstance(row, dict):
            raise PriceProviderError(f"{source}: expected bar objects, got {type(row).__name__}")
        bars.append(
            RawPriceBar(
                trade_date=_date_part(row.get("date")),
                open=_to_str(row.get("open")),
                high=_to_str(row.get("high")),
                low=_to_str(row.get("low")),
                close=_to_str(row.get("close")),
                adj_close=_to_str(row.get("adjClose")),
                volume=_to_str(row.get("volume")),
            )
        )
    return bars


class TiingoDailyPriceProvider:
    """Fetches daily OHLCV from Tiingo. One implementation of :class:`DailyPriceProvider`."""

    source_name = SOURCE_NAME

    def __init__(
        self,
        *,
        token: str,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.Client | None = None,
        timeout: float = _REQUEST_TIMEOUT,
    ) -> None:
        if token is None or token.strip() == "":
            raise PriceProviderConfigError(
                f"{SOURCE_NAME}: API token is not configured. {_TOKEN_HELP}"
            )
        self._token = token.strip()
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._timeout = timeout

    def fetch_daily_history(self, ticker: str, *, start: date, end: date) -> list[RawPriceBar]:
        symbol = ticker.strip().upper()
        url = f"{self._base_url}/tiingo/daily/{symbol}/prices"
        params = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "format": "json",
        }
        headers = {"Authorization": f"Token {self._token}", "Accept": "application/json"}
        logger.info(
            "tiingo.http_get",
            extra={"symbol": symbol, "start": params["startDate"], "end": params["endDate"]},
        )

        try:
            if self._client is not None:
                response = self._client.get(url, params=params, headers=headers)
            else:
                with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                    response = client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:  # connect/read/timeout/DNS - never leak httpx upward
            raise PriceProviderError(
                f"{SOURCE_NAME}: network error contacting {url}: {exc!r}"
            ) from exc

        code = response.status_code
        if code in (401, 403):
            raise PriceProviderAuthError(
                f"{SOURCE_NAME}: HTTP {code} - credentials rejected. {_TOKEN_HELP}"
            )
        if code == 404:
            raise PriceDataUnavailableError(f"{SOURCE_NAME}: HTTP 404 for {symbol}")
        if code == 429:
            raise PriceProviderRateLimitedError(f"{SOURCE_NAME}: HTTP 429 (rate limited)")
        if code >= 400:
            raise PriceProviderError(f"{SOURCE_NAME}: HTTP {code}: {response.text[:200]!r}")

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise PriceProviderError(
                f"{SOURCE_NAME}: non-JSON response ({response.text[:200]!r})"
            ) from exc

        bars = parse_tiingo_eod(payload, self.source_name)
        logger.info("tiingo.fetched", extra={"symbol": symbol, "bars": len(bars)})
        return bars
