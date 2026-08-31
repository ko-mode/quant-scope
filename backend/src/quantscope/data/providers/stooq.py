"""Stooq adapter for daily price history (Phase 1C development provider).

Endpoint: ``https://stooq.com/q/d/l/?s=<symbol>&i=d&d1=<YYYYMMDD>&d2=<YYYYMMDD>``
returning CSV ``Date,Open,High,Low,Close,Volume``. US symbols use a ``.us``
suffix and ``.`` in a ticker becomes ``-`` (``BRK.B`` -> ``brk-b.us``).

**Known limitations (ADR 0022):**

* **Anti-bot gating (verified 2026-08-30):** every Stooq data URL currently
  responds ``200`` with a JavaScript proof-of-work "verify your browser"
  challenge page instead of CSV. A plain HTTP client cannot fetch data. This
  adapter detects the challenge and raises :class:`PriceProviderBlockedError`;
  it is unit-tested but **cannot be verified against a live Stooq response**
  until the gating is lifted or a JS-capable fetch path is added.
* Stooq serves a **single** ``Close`` column - no separate raw/unadjusted price.
  This adapter maps ``Close`` to both ``close`` and ``adj_close``. Whether that
  series is split- and/or dividend-adjusted is **assumed, not verified**.
* Historically Stooq also throttles to ~50-100 requests/day per IP, returning
  ``"Exceeded the daily hits limit"`` - surfaced as
  :class:`PriceProviderRateLimitedError`.

No Stooq response is ever committed to the repository (ADR 0015); tests use
synthetic CSV strings.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date

import httpx

from quantscope.data.providers.base import (
    PriceDataUnavailableError,
    PriceProviderBlockedError,
    PriceProviderError,
    PriceProviderRateLimitedError,
    RawPriceBar,
)

logger = logging.getLogger(__name__)

SOURCE_NAME = "stooq"
_EXPECTED_HEADER = ("date", "open", "high", "low", "close", "volume")
_MISSING_TOKENS = frozenset({"", "n/d", "-", "null", "nan"})
_REQUEST_TIMEOUT = 30.0


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return None if text.lower() in _MISSING_TOKENS else text


def parse_stooq_csv(text: str, source: str = SOURCE_NAME) -> list[RawPriceBar]:
    """Parse a Stooq daily CSV body into raw bars (pure; no I/O)."""
    body = text.strip()
    lowered = body.lower()
    if "exceeded" in lowered and "limit" in lowered:
        raise PriceProviderRateLimitedError(f"{source}: {body[:200]}")
    if "verify your browser" in lowered or "requires javascript" in lowered:
        raise PriceProviderBlockedError(
            f"{source}: served a browser-verification challenge instead of CSV"
        )
    if body == "":
        raise PriceDataUnavailableError(f"{source}: <empty response>")
    if lowered.startswith("no data") or "<html" in lowered or "<!doctype" in lowered:
        raise PriceDataUnavailableError(f"{source}: {body[:200]}")

    reader = csv.reader(io.StringIO(body))
    try:
        header = [h.strip().lower() for h in next(reader)]
    except StopIteration as exc:
        raise PriceDataUnavailableError(f"{source}: empty CSV") from exc
    missing_columns = [name for name in _EXPECTED_HEADER if name not in header]
    if missing_columns:
        raise PriceProviderError(
            f"{source}: CSV header missing {missing_columns!r} (got {header!r})"
        )

    idx = {name: header.index(name) for name in _EXPECTED_HEADER}
    bars: list[RawPriceBar] = []
    for row in reader:
        if len(row) < len(_EXPECTED_HEADER):
            logger.warning("stooq.short_row", extra={"row": row})
            continue
        close = _clean(row[idx["close"]])
        bars.append(
            RawPriceBar(
                trade_date=_clean(row[idx["date"]]),
                open=_clean(row[idx["open"]]),
                high=_clean(row[idx["high"]]),
                low=_clean(row[idx["low"]]),
                close=close,
                adj_close=close,  # Stooq serves one adjusted series (see module docstring)
                volume=_clean(row[idx["volume"]]),
            )
        )
    return bars


class StooqDailyPriceProvider:
    """Fetches daily OHLCV from Stooq. Replaceable behind :class:`DailyPriceProvider`."""

    source_name = SOURCE_NAME

    def __init__(
        self,
        *,
        base_url: str = "https://stooq.com/q/d/l/",
        client: httpx.Client | None = None,
        timeout: float = _REQUEST_TIMEOUT,
    ) -> None:
        self._base_url = base_url
        self._client = client
        self._timeout = timeout

    @staticmethod
    def _symbol(ticker: str) -> str:
        return f"{ticker.strip().lower().replace('.', '-')}.us"

    def fetch_daily_history(self, ticker: str, *, start: date, end: date) -> list[RawPriceBar]:
        params = {
            "s": self._symbol(ticker),
            "i": "d",
            "d1": start.strftime("%Y%m%d"),
            "d2": end.strftime("%Y%m%d"),
        }
        logger.info(
            "stooq.http_get", extra={"symbol": params["s"], "d1": params["d1"], "d2": params["d2"]}
        )
        if self._client is not None:
            response = self._client.get(self._base_url, params=params)
        else:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                response = client.get(self._base_url, params=params)

        if response.status_code == 429:
            raise PriceProviderRateLimitedError(f"{self.source_name}: HTTP 429")
        if response.status_code == 404:
            raise PriceDataUnavailableError(f"{self.source_name}: HTTP 404 for {params['s']}")
        if response.status_code >= 400:
            raise PriceProviderError(
                f"{self.source_name}: HTTP {response.status_code} for {params['s']}"
            )
        bars = parse_stooq_csv(response.text, self.source_name)
        logger.info("stooq.fetched", extra={"symbol": params["s"], "bars": len(bars)})
        return bars
