"""``parse_company_tickers_exchange`` - synthetic payloads only."""

from __future__ import annotations

import pytest

from quantscope.data.providers.base import RawSecurityRecord
from quantscope.data.providers.sec_edgar import (
    SecReferenceDataError,
    parse_company_tickers_exchange,
)


def test_parses_standard_payload() -> None:
    payload = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"]],
    }
    assert parse_company_tickers_exchange(payload) == [
        RawSecurityRecord(ticker="AAPL", name="Apple Inc.", cik="320193", exchange="Nasdaq")
    ]


def test_locates_columns_by_header_not_position() -> None:
    payload = {
        "fields": ["ticker", "exchange", "cik", "name"],
        "data": [["MSFT", "Nasdaq", 789019, "MICROSOFT CORP"]],
    }
    (record,) = parse_company_tickers_exchange(payload)
    assert record == RawSecurityRecord(
        ticker="MSFT", name="MICROSOFT CORP", cik="789019", exchange="Nasdaq"
    )


def test_blank_and_null_cells_become_none() -> None:
    payload = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [[None, "  ", "NEW", ""]],
    }
    (record,) = parse_company_tickers_exchange(payload)
    assert record == RawSecurityRecord(ticker="NEW", name=None, cik=None, exchange=None)


def test_short_rows_are_skipped() -> None:
    payload = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [[1, "Whole Co", "OK", "NYSE"], [2, "Truncated"]],
    }
    records = parse_company_tickers_exchange(payload)
    assert [r.ticker for r in records] == ["OK"]


@pytest.mark.parametrize(
    "payload",
    [
        {"data": []},
        {"fields": ["cik", "name", "ticker", "exchange"]},
        {"fields": "nope", "data": []},
        {"fields": ["cik", "name", "ticker"], "data": []},
        ["not", "a", "dict"],
    ],
)
def test_malformed_documents_raise(payload: object) -> None:
    with pytest.raises(SecReferenceDataError):
        parse_company_tickers_exchange(payload)
