"""Guarded live Tiingo smoke tests (ADR 0022).

Runs only when ``QUANTSCOPE_TIINGO_TOKEN`` is set; otherwise the whole module is
skipped. Fetched data is used in-memory only and never persisted or committed.
"""

from __future__ import annotations

import os
from datetime import date

import httpx
import pytest

from quantscope.data.providers.tiingo import DEFAULT_BASE_URL, TiingoDailyPriceProvider
from quantscope.data.spot_checks import (
    check_nvda_split_adjustment,
    verify_dividend_back_adjustment,
)
from quantscope.data.validation import normalize_and_validate

_TOKEN = os.environ.get("QUANTSCOPE_TIINGO_TOKEN", "")
_BASE_URL = os.environ.get("QUANTSCOPE_TIINGO_BASE_URL", DEFAULT_BASE_URL)

pytestmark = pytest.mark.skipif(
    not _TOKEN,
    reason="set QUANTSCOPE_TIINGO_TOKEN to run live Tiingo tests",
)

DEMO_TICKERS = ("NVDA", "AMD", "INTC", "AAPL", "MSFT", "SPY")
_START = date(2015, 1, 1)
_END = date(2025, 1, 31)


@pytest.fixture(scope="module")
def provider() -> TiingoDailyPriceProvider:
    return TiingoDailyPriceProvider(token=_TOKEN, base_url=_BASE_URL)


@pytest.mark.parametrize("ticker", DEMO_TICKERS)
def test_demo_ticker_fetch_normalizes_and_validates(
    provider: TiingoDailyPriceProvider, ticker: str
) -> None:
    bars = provider.fetch_daily_history(ticker, start=_START, end=_END)
    result = normalize_and_validate(bars, source=provider.source_name)
    frame = result.valid

    print(
        f"\n[{ticker}] raw={len(bars)}  valid={len(frame)}  "
        f"dropped={len(bars) - len(frame)}  errors={result.error_counts}"
    )
    if not frame.empty:
        print(
            f"[{ticker}] range {frame['trade_date'].min().date()} .. "
            f"{frame['trade_date'].max().date()}"
        )

    assert len(frame) > 2000, f"{ticker}: expected multi-year history"
    assert frame["trade_date"].is_monotonic_increasing
    assert frame["trade_date"].is_unique
    assert (frame["close"] > 0).all()
    assert (frame["adj_close"] > 0).all()
    assert result.error_counts == {}, f"{ticker}: unexpected validation drops"


def test_nvda_split_spot_check_live(provider: TiingoDailyPriceProvider) -> None:
    bars = provider.fetch_daily_history("NVDA", start=date(2024, 5, 1), end=date(2024, 7, 31))
    frame = normalize_and_validate(bars, source=provider.source_name).valid
    result = check_nvda_split_adjustment(frame)
    print("\n[NVDA split spot-check]")
    for line in result.observations:
        print(f"  - {line}")
    assert result.passed, result.observations
    assert result.ratio_across_split is not None
    assert 0.85 <= result.ratio_across_split <= 1.15


def _raw_tiingo(ticker: str, start: date, end: date) -> list[dict]:
    """Direct fetch of the raw Tiingo payload (keeps divCash / splitFactor)."""
    resp = httpx.get(
        f"{_BASE_URL.rstrip('/')}/tiingo/daily/{ticker}/prices",
        params={"startDate": start.isoformat(), "endDate": end.isoformat(), "format": "json"},
        headers={"Authorization": f"Token {_TOKEN}", "Accept": "application/json"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return list(resp.json())


def test_dividend_back_adjustment_semantics_live() -> None:
    """Empirically check whether Tiingo's adjClose folds a dividend in.

    Uses a split-free AAPL quarter and locates the single ex-dividend session
    (divCash > 0) rather than hard-coding a date or amount.
    """
    rows = _raw_tiingo("AAPL", date(2024, 4, 20), date(2024, 6, 1))
    rows.sort(key=lambda r: r["date"])

    ex_positions = [i for i, r in enumerate(rows) if float(r.get("divCash") or 0) > 0]
    if len(ex_positions) != 1:
        pytest.skip(
            f"expected exactly one AAPL ex-dividend session in the window, found {len(ex_positions)}"
        )
    i = ex_positions[0]
    if i == 0:
        pytest.skip("ex-dividend session is the first row; widen the window")

    before, ex = rows[i - 1], rows[i]
    result = verify_dividend_back_adjustment(
        close_before=float(before["close"]),
        close_ex=float(ex["close"]),
        adj_close_before=float(before["adjClose"]),
        adj_close_ex=float(ex["adjClose"]),
        dividend=float(ex["divCash"]),
        split_factor_ex=float(ex.get("splitFactor") or 1.0),
    )
    print(f"\n[AAPL dividend semantics]  ex-date {ex['date'][:10]}  divCash {ex['divCash']}")
    for line in result.observations:
        print(f"  - {line}")

    # If this fails, Tiingo's adjClose is NOT a total-return series and ADR 0012's
    # `adj_close.pct_change()` assumption is contradicted - do not paper over it.
    assert result.dividend_incorporated, result.observations
