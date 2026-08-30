"""Normalisation of CIK, ticker, exchange, and whole records."""

from __future__ import annotations

import pytest

from quantscope.data.providers.base import RawSecurityRecord
from quantscope.data.reference import (
    RECOGNISED_EXCHANGES,
    SUPPORTED_EXCHANGES,
    InvalidCikError,
    NormalizedSecurity,
    RejectedRecord,
    normalize_cik,
    normalize_exchange,
    normalize_record,
    normalize_ticker,
)


# --------------------------------------------------------------------------- #
# CIK
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (320193, "0000320193"),
        ("320193", "0000320193"),
        ("0000320193", "0000320193"),
        ("0001045810", "0001045810"),
        ("1", "0000000001"),
        ("0000000000", "0000000000"),
    ],
)
def test_normalize_cik_pads_to_ten_digits(raw: str | int, expected: str) -> None:
    assert normalize_cik(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_normalize_cik_absent_is_none(raw: str | None) -> None:
    assert normalize_cik(raw) is None


@pytest.mark.parametrize("raw", ["12A45", "12345678901", "999999999999", "0x1F", "12 34"])
def test_normalize_cik_malformed_raises(raw: str) -> None:
    with pytest.raises(InvalidCikError):
        normalize_cik(raw)


# --------------------------------------------------------------------------- #
# ticker
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [("aapl", "AAPL"), (" msft ", "MSFT"), ("BRK-B", "BRK-B"), ("BF.B", "BF.B")],
)
def test_normalize_ticker_ok(raw: str, expected: str) -> None:
    assert normalize_ticker(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "A B", "TOO$LONG", "X" * 33, "eur/usd"])
def test_normalize_ticker_unusable_is_none(raw: str | None) -> None:
    assert normalize_ticker(raw) is None


# --------------------------------------------------------------------------- #
# exchange
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("NYSE", "XNYS"),
        ("nyse", "XNYS"),
        ("Nasdaq", "XNAS"),
        ("  NASDAQ  ", "XNAS"),
        ("NYSE American", "XASE"),
        ("NYSE MKT", "XASE"),
        ("AMEX", "XASE"),
        ("NYSE Arca", "ARCX"),
        ("Cboe", "BATS"),
        ("BATS", "BATS"),
        ("IEX", "IEXG"),
        ("OTC", "OTC"),
    ],
)
def test_normalize_exchange_maps_known_labels(raw: str, expected: str) -> None:
    assert normalize_exchange(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "Toronto", "LSE", "unknown"])
def test_normalize_exchange_unknown_is_none(raw: str | None) -> None:
    assert normalize_exchange(raw) is None


# --------------------------------------------------------------------------- #
# whole record
# --------------------------------------------------------------------------- #
def _raw(**kw: str | None) -> RawSecurityRecord:
    base: dict[str, str | None] = {
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "cik": "320193",
        "exchange": "Nasdaq",
    }
    base.update(kw)
    return RawSecurityRecord(**base)


def test_normalize_record_happy_path() -> None:
    result = normalize_record(_raw())
    assert result == NormalizedSecurity(
        ticker="AAPL", name="Apple Inc.", cik="0000320193", exchange="XNAS", asset_type=None
    )


def test_normalize_record_curated_etf_gets_asset_type() -> None:
    result = normalize_record(
        _raw(ticker="SPY", name="SPDR S&P 500 ETF TRUST", exchange="NYSE Arca")
    )
    assert isinstance(result, NormalizedSecurity)
    assert result.asset_type == "etf"


def test_normalize_record_missing_cik_is_allowed_as_null() -> None:
    result = normalize_record(_raw(cik=None))
    assert isinstance(result, NormalizedSecurity)
    assert result.cik is None


@pytest.mark.parametrize(
    ("overrides", "reason_prefix"),
    [
        ({"ticker": ""}, "invalid_or_missing_ticker"),
        ({"ticker": None}, "invalid_or_missing_ticker"),
        ({"name": "   "}, "missing_name"),
        ({"cik": "12A"}, "invalid_cik"),
        ({"cik": "999999999999"}, "invalid_cik"),
        ({"exchange": None}, "unmapped_or_missing_exchange"),
        ({"exchange": "Toronto"}, "unmapped_or_missing_exchange"),
        ({"exchange": "OTC"}, "unsupported_exchange_v1"),
        ({"exchange": "otc"}, "unsupported_exchange_v1"),
    ],
)
def test_normalize_record_rejections(overrides: dict[str, str | None], reason_prefix: str) -> None:
    result = normalize_record(_raw(**overrides))
    assert isinstance(result, RejectedRecord)
    assert result.reason.split(":", 1)[0] == reason_prefix


def test_normalize_record_rejects_otc_with_recognised_code() -> None:
    """OTC is recognised (mapped) but excluded from the V1 universe."""
    result = normalize_record(_raw(exchange="OTC"))
    assert isinstance(result, RejectedRecord)
    assert result.reason == "unsupported_exchange_v1:OTC"


def test_supported_excludes_only_otc() -> None:
    assert "OTC" in RECOGNISED_EXCHANGES
    assert "OTC" not in SUPPORTED_EXCHANGES
    assert RECOGNISED_EXCHANGES - {"OTC"} == SUPPORTED_EXCHANGES
    assert {"XNYS", "XNAS", "XASE", "ARCX", "BATS", "IEXG"} <= SUPPORTED_EXCHANGES
