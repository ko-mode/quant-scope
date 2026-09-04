"""Normalising + validating raw Kenneth French factor records.

Golden values for the percent -> decimal conversion are computed by hand, not
from the implementation: ``0.25`` (percent) -> ``0.0025`` (decimal daily return).
"""

from __future__ import annotations

import pytest

from quantscope.data.factors import normalize_and_validate_factors, normalize_factor_returns
from quantscope.data.providers.base import RawFactorReturn

_SOURCE = "kenneth_french"


def _rec(date: str, name: str, value: str | None) -> RawFactorReturn:
    return RawFactorReturn(trade_date=date, factor_name=name, value=value)


def test_percent_to_decimal_conversion() -> None:
    cases = [
        ("0.25", 0.0025),
        ("-0.24", -0.0024),
        ("0.009", 0.00009),
        ("100.00", 1.0),  # arithmetic is exact even though this row is later rejected
        ("0", 0.0),
    ]
    for percent_text, expected_decimal in cases:
        result = normalize_and_validate_factors(
            [_rec("20240102", "rf", percent_text)], source=_SOURCE
        )
        normalized = normalize_factor_returns(
            [_rec("20240102", "rf", percent_text)], source=_SOURCE
        )
        assert normalized.frame["value"].iloc[0] == pytest.approx(expected_decimal)
        # only in-bounds conversions are eligible for persistence
        if abs(expected_decimal) < 0.5:
            assert len(result.valid) == 1
        else:
            assert len(result.valid) == 0


def test_all_four_factor_names_persist() -> None:
    raw = [
        _rec("20240102", "mkt_rf", "0.10"),
        _rec("20240102", "SMB", "-0.20"),  # case-insensitive
        _rec("20240102", "hml", "0.30"),
        _rec("20240102", "RF", "0.01"),
    ]
    result = normalize_and_validate_factors(raw, source=_SOURCE)
    assert result.ok
    assert set(result.valid["factor_name"]) == {"mkt_rf", "smb", "hml", "rf"}
    assert set(result.valid["frequency"]) == {"daily"}
    assert set(result.valid["source"]) == {_SOURCE}


def test_unknown_factor_name_is_dropped() -> None:
    result = normalize_and_validate_factors([_rec("20240102", "momentum", "0.10")], source=_SOURCE)
    assert not result.ok
    assert result.error_counts == {"unknown_factor_name": 1}
    assert len(result.valid) == 0


def test_invalid_date_is_dropped() -> None:
    result = normalize_and_validate_factors([_rec("not-a-date", "rf", "0.01")], source=_SOURCE)
    assert result.error_counts == {"invalid_trade_date": 1}


def test_malformed_number_is_dropped() -> None:
    result = normalize_and_validate_factors([_rec("20240102", "rf", "abc")], source=_SOURCE)
    assert result.error_counts == {"malformed_numeric": 1}


def test_missing_value_sentinel_is_rejected_not_coerced() -> None:
    for sentinel in ("-99.99", "-999", "-999.0"):
        result = normalize_and_validate_factors(
            [_rec("20240102", "mkt_rf", sentinel)], source=_SOURCE
        )
        assert result.error_counts == {"missing_factor_value": 1}, sentinel
        assert len(result.valid) == 0


def test_duplicate_date_factor_source_is_rejected() -> None:
    raw = [_rec("20240102", "rf", "0.01"), _rec("20240102", "rf", "0.02")]
    result = normalize_and_validate_factors(raw, source=_SOURCE)
    # both rows share (date, factor, source), so they collapse to one reported
    # reason, but neither reaches `valid` - the PK could not accept either.
    assert result.error_counts == {"duplicate_factor_key": 1}
    assert len(result.valid) == 0


def test_percent_vs_decimal_confusion_is_caught() -> None:
    # A caller that forgot to convert (or passed an already-decimal 25%) would
    # produce values far outside any real daily factor return.
    result = normalize_and_validate_factors(
        [_rec("20240102", "mkt_rf", "60")],
        source=_SOURCE,  # -> 0.60 decimal
    )
    assert result.error_counts == {"value_out_of_decimal_bounds": 1}
    assert len(result.valid) == 0


def test_empty_value_is_dropped() -> None:
    result = normalize_and_validate_factors([_rec("20240102", "rf", "")], source=_SOURCE)
    assert result.error_counts == {"missing_required_value": 1}


def test_no_input_returns_empty_frame() -> None:
    result = normalize_and_validate_factors([], source=_SOURCE)
    assert result.ok
    assert len(result.valid) == 0
