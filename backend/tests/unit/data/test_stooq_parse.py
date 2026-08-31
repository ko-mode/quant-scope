"""Stooq CSV parsing and the adapter's HTTP behaviour (synthetic responses only)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest

from quantscope.data.providers.base import (
    PriceDataUnavailableError,
    PriceProviderBlockedError,
    PriceProviderError,
    PriceProviderRateLimitedError,
)
from quantscope.data.providers.stooq import (
    StooqDailyPriceProvider,
    parse_stooq_csv,
)

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "prices"


def test_parses_sample_csv() -> None:
    bars = parse_stooq_csv((_FIXTURES / "stooq_nvda_sample.csv").read_text())
    assert len(bars) == 6
    first = bars[0]
    assert (first.trade_date, first.open, first.close, first.volume) == (
        "2020-01-02",
        "5.97",
        "5.99",
        "237536000",
    )
    # Stooq serves a single price series -> adj_close mirrors close.
    assert first.adj_close == first.close
    # "N/D" is a Stooq missing token -> None.
    assert bars[-1].volume is None


def test_column_order_from_header_not_position() -> None:
    csv = "Volume,Close,Date,Low,High,Open\n1000,10.5,2024-01-02,9.9,10.6,10.0\n"
    (bar,) = parse_stooq_csv(csv)
    assert (bar.trade_date, bar.open, bar.high, bar.low, bar.close, bar.volume) == (
        "2024-01-02",
        "10.0",
        "10.6",
        "9.9",
        "10.5",
        "1000",
    )


def test_rate_limit_body_raises() -> None:
    with pytest.raises(PriceProviderRateLimitedError):
        parse_stooq_csv("Exceeded the daily hits limit, please try again tomorrow")


def test_browser_verification_challenge_raises_blocked() -> None:
    challenge = (
        '<!DOCTYPE html><html><head><meta name="robots" content="noindex,nofollow">'
        "</head><body><noscript>This site requires JavaScript to verify your browser."
        "</noscript><script>/* proof of work */</script></body></html>"
    )
    with pytest.raises(PriceProviderBlockedError):
        parse_stooq_csv(challenge)


@pytest.mark.parametrize("body", ["", "No data", "<html><body>error</body></html>"])
def test_unavailable_bodies_raise(body: str) -> None:
    with pytest.raises(PriceDataUnavailableError):
        parse_stooq_csv(body)


def test_unexpected_header_raises() -> None:
    with pytest.raises(PriceProviderError):
        parse_stooq_csv("Time,Price\n2024-01-02,10\n")


def test_short_rows_skipped() -> None:
    csv = "Date,Open,High,Low,Close,Volume\n2024-01-02,1,2,0.5,1.5,10\n2024-01-03,oops\n"
    bars = parse_stooq_csv(csv)
    assert [b.trade_date for b in bars] == ["2024-01-02"]


def _mock_client(body: str, status: int = 200) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(lambda _req: httpx.Response(status, text=body))
    )


def test_symbol_mapping() -> None:
    assert StooqDailyPriceProvider._symbol("NVDA") == "nvda.us"
    assert StooqDailyPriceProvider._symbol("BRK.B") == "brk-b.us"


def test_fetch_daily_history_uses_client() -> None:
    body = "Date,Open,High,Low,Close,Volume\n2024-06-10,120,123,118,121.8,300000000\n"
    provider = StooqDailyPriceProvider(client=_mock_client(body))
    bars = provider.fetch_daily_history("NVDA", start=date(2024, 6, 1), end=date(2024, 6, 30))
    assert [b.close for b in bars] == ["121.8"]


def test_fetch_http_429_raises_rate_limited() -> None:
    provider = StooqDailyPriceProvider(client=_mock_client("", status=429))
    with pytest.raises(PriceProviderRateLimitedError):
        provider.fetch_daily_history("NVDA", start=date(2024, 1, 1), end=date(2024, 2, 1))
