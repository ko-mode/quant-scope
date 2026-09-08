"""Pandera validation of the canonical price frame + `normalize_and_validate`."""

from __future__ import annotations

import pandas as pd
import pytest

from quantscope.data.prices import normalize_price_bars
from quantscope.data.providers.base import RawPriceBar
from quantscope.data.validation import normalize_and_validate, validate_price_bars


def _raw(row: dict[str, str]) -> RawPriceBar:
    """Build one bar. OHLC defaults are derived from `close` so a row is
    internally consistent unless a test overrides high/low explicitly.
    """
    close = row.get("close", "121.8")
    adj_close = row.get("adj_close", close)
    try:
        c = float(close)
        d_open = row.get("open", f"{c:.2f}")
        d_high = row.get("high", f"{c * 1.03:.2f}")
        d_low = row.get("low", f"{c * 0.97:.2f}")
    except ValueError:  # non-numeric close on purpose
        d_open, d_high, d_low = (
            row.get("open", "120"),
            row.get("high", "123"),
            row.get("low", "118"),
        )
    return RawPriceBar(
        row.get("trade_date", "2024-06-10"),
        d_open,
        d_high,
        d_low,
        close,
        adj_close,
        row.get("volume", "300000000"),
    )


def _frame(rows: list[dict[str, str]]) -> pd.DataFrame:
    return normalize_price_bars([_raw(r) for r in rows], source="stooq").frame


def test_clean_frame_passes() -> None:
    frame = _frame(
        [
            {"trade_date": "2024-06-10"},
            {"trade_date": "2024-06-11", "close": "120.9", "adj_close": "120.9"},
        ]
    )
    result = validate_price_bars(frame)
    assert result.ok
    assert len(result.valid) == 2


@pytest.mark.parametrize(
    ("rows", "code", "column"),
    [
        ([{"close": "0", "adj_close": "0"}], "non_positive_price", "close"),
        ([{"close": "-1", "adj_close": "-1"}], "non_positive_price", "close"),
        ([{"open": "0"}], "non_positive_price", "open"),
        ([{"high": "100", "low": "110"}], "impossible_high_low", None),
        ([{"volume": "-5"}], "negative_volume", "volume"),
        ([{"trade_date": "2024-06-08"}], "non_session_trade_date", "trade_date"),  # Saturday
        (
            [{"trade_date": "2024-06-19"}],
            "non_session_trade_date",
            "trade_date",
        ),  # Juneteenth holiday
    ],
)
def test_row_level_rejections(rows: list[dict[str, str]], code: str, column: str | None) -> None:
    result = validate_price_bars(_frame(rows))
    assert not result.ok
    assert code in result.error_counts
    if column is not None:
        assert any(e.column == column and e.code == code for e in result.errors)
    assert len(result.valid) == 0  # the only row was rejected


def test_non_session_row_rejected_but_real_sessions_in_the_same_frame_survive() -> None:
    # QS-01: a bad (non-session) row is rejected on its own - it never poisons
    # an otherwise-valid history.
    frame = _frame(
        [
            {"trade_date": "2024-06-10"},  # Monday - real session
            {"trade_date": "2024-06-08", "close": "999", "adj_close": "999"},  # Saturday
            {"trade_date": "2024-06-11", "close": "121.0", "adj_close": "121.0"},  # Tuesday
        ]
    )
    result = validate_price_bars(frame)
    assert "non_session_trade_date" in result.error_counts
    assert len(result.valid) == 2
    assert {pd.Timestamp(d).date().isoformat() for d in result.valid["trade_date"]} == {
        "2024-06-10",
        "2024-06-11",
    }


def test_duplicate_trade_date_source_rejected_and_both_rows_excluded() -> None:
    frame = _frame(
        [
            {"trade_date": "2024-06-10"},
            {"trade_date": "2024-06-10", "close": "999", "adj_close": "999"},
        ]
    )
    result = validate_price_bars(frame)
    assert "duplicate_trade_date_source" in result.error_counts
    assert len(result.valid) == 0


def test_valid_subset_returned_alongside_errors() -> None:
    frame = _frame(
        [
            {"trade_date": "2024-06-10"},
            {"trade_date": "2024-06-11", "close": "0", "adj_close": "0"},
            {"trade_date": "2024-06-12", "close": "125.2", "adj_close": "125.2"},
        ]
    )
    result = validate_price_bars(frame)
    assert not result.ok
    assert list(result.valid["trade_date"]) == [
        pd.Timestamp("2024-06-10"),
        pd.Timestamp("2024-06-12"),
    ]


def test_normalize_and_validate_merges_parse_and_validation_errors() -> None:
    raw = [
        RawPriceBar("2024-06-10", "120", "123", "118", "121.8", "121.8", "300000000"),
        RawPriceBar("2024-06-11", "1", "2", "0.5", "bad", "bad", "10"),  # malformed -> parse error
        RawPriceBar("2024-06-12", "1", "2", "3", "5", "5", "10"),  # low>high -> validation error
    ]
    result = normalize_and_validate(raw, source="stooq")
    codes = result.error_counts
    assert "malformed_numeric" in codes
    assert "impossible_high_low" in codes
    assert list(result.valid["trade_date"]) == [pd.Timestamp("2024-06-10")]


def test_empty_frame_is_ok_and_empty() -> None:
    result = normalize_and_validate([], source="stooq")
    assert result.ok
    assert result.valid.empty


def test_error_as_dict_shape() -> None:
    result = validate_price_bars(_frame([{"close": "0", "adj_close": "0"}]))
    payload = result.errors[0].as_dict()
    assert set(payload) == {"code", "column", "trade_date", "detail"}
