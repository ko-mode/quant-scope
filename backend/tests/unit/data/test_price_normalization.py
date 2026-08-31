"""`normalize_price_bars`: raw provider bars -> canonical typed frame + drop reasons."""

from __future__ import annotations

import math

import pandas as pd

from quantscope.data.prices import PRICE_BAR_COLUMNS, normalize_price_bars
from quantscope.data.providers.base import RawPriceBar


def _bar(
    trade_date: str | None = "2024-06-10",
    *,
    open_: str | None = "120.0",
    high: str | None = "123.0",
    low: str | None = "118.0",
    close: str | None = "121.8",
    adj_close: str | None = "121.8",
    volume: str | None = "300000000",
) -> RawPriceBar:
    return RawPriceBar(trade_date, open_, high, low, close, adj_close, volume)


def test_clean_input_produces_typed_ordered_frame() -> None:
    result = normalize_price_bars(
        [_bar("2024-06-11", close="120.9", adj_close="120.9"), _bar("2024-06-10")],
        source="stooq",
    )
    frame = result.frame
    assert result.parse_errors == ()
    assert list(frame.columns) == list(PRICE_BAR_COLUMNS)
    assert str(frame["trade_date"].dtype) == "datetime64[ns]"
    assert str(frame["close"].dtype) == "float64"
    assert str(frame["volume"].dtype) == "Int64"
    assert str(frame["source"].dtype) == "string"
    # sorted ascending by trade_date
    assert list(frame["trade_date"]) == [pd.Timestamp("2024-06-10"), pd.Timestamp("2024-06-11")]
    assert (frame["source"] == "stooq").all()


def test_missing_optional_values_kept_as_nan_never_zero() -> None:
    result = normalize_price_bars(
        [_bar(open_=None, high=None, low=None, volume=None)], source="stooq"
    )
    row = result.frame.iloc[0]
    assert math.isnan(row["open"]) and math.isnan(row["high"]) and math.isnan(row["low"])
    assert pd.isna(row["volume"])
    assert row["close"] == 121.8  # required value untouched
    assert result.parse_errors == ()


def test_malformed_numeric_drops_row_with_reason() -> None:
    result = normalize_price_bars(
        [_bar(close="1.2.3"), _bar("2024-06-11", close="120.9", adj_close="120.9")],
        source="stooq",
    )
    assert len(result.frame) == 1
    assert list(result.frame["trade_date"]) == [pd.Timestamp("2024-06-11")]
    (err,) = result.parse_errors
    assert err.code == "malformed_numeric"
    assert err.column == "close"
    assert err.trade_date == "2024-06-10"


def test_invalid_trade_date_drops_row_with_reason() -> None:
    result = normalize_price_bars([_bar("2024-13-45"), _bar("2024-06-10")], source="stooq")
    assert list(result.frame["trade_date"]) == [pd.Timestamp("2024-06-10")]
    assert [e.code for e in result.parse_errors] == ["invalid_trade_date"]


def test_missing_required_close_drops_row_with_reason() -> None:
    result = normalize_price_bars([_bar(close="", adj_close="")], source="stooq")
    assert result.frame.empty
    # one reason per dropped row; `close` is checked first
    assert [e.code for e in result.parse_errors] == ["missing_required_value"]
    assert result.parse_errors[0].column == "close"


def test_negative_volume_survives_normalization() -> None:
    # sign checks are validation's job, not normalization's
    result = normalize_price_bars([_bar(volume="-5")], source="stooq")
    assert result.frame.iloc[0]["volume"] == -5
    assert result.parse_errors == ()


def test_empty_input_yields_empty_typed_frame() -> None:
    result = normalize_price_bars([], source="stooq")
    assert result.frame.empty
    assert list(result.frame.columns) == list(PRICE_BAR_COLUMNS)
    assert str(result.frame["trade_date"].dtype) == "datetime64[ns]"
