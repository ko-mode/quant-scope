"""Boundary validation: `validate_price_series` / `validate_return_series`."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantscope.quant.frames import validate_price_series, validate_return_series
from quantscope.quant.results import QuantInputError


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2023-01-02", periods=n)


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=_dates(len(values)), dtype="float64")


def test_clean_price_series_passes_and_is_float64() -> None:
    out = validate_price_series(_series([100.0, 101.5, 99.25]))
    assert out.dtype == np.dtype("float64")
    assert list(out) == [100.0, 101.5, 99.25]


def test_integer_prices_are_coerced_to_float() -> None:
    raw = pd.Series([100, 101, 102], index=_dates(3))
    out = validate_price_series(raw)
    assert out.dtype == np.dtype("float64")


def test_return_series_allows_zero_variance_and_negatives() -> None:
    validate_return_series(_series([-0.01, -0.01, -0.01]))
    validate_return_series(_series([-0.2, 0.0, 0.35]))


def test_empty_series_rejected() -> None:
    with pytest.raises(QuantInputError, match="empty"):
        validate_price_series(pd.Series([], dtype="float64", index=pd.DatetimeIndex([])))


def test_non_datetime_index_rejected() -> None:
    with pytest.raises(QuantInputError, match="DatetimeIndex"):
        validate_price_series(pd.Series([100.0, 101.0, 102.0]))


def test_unsorted_index_rejected() -> None:
    idx = pd.to_datetime(["2023-01-03", "2023-01-02", "2023-01-04"])
    with pytest.raises(QuantInputError, match="sorted ascending"):
        validate_price_series(pd.Series([100.0, 101.0, 102.0], index=idx))


def test_duplicate_index_rejected() -> None:
    idx = pd.to_datetime(["2023-01-02", "2023-01-02", "2023-01-03"])
    with pytest.raises(QuantInputError, match="duplicate dates"):
        validate_price_series(pd.Series([100.0, 101.0, 102.0], index=idx))


def test_nan_value_rejected() -> None:
    with pytest.raises(QuantInputError):
        validate_price_series(_series([100.0, np.nan, 102.0]))


def test_inf_value_rejected() -> None:
    with pytest.raises(QuantInputError):
        validate_return_series(_series([0.01, np.inf, -0.01]))


@pytest.mark.parametrize("bad", [0.0, -1.5])
def test_non_positive_price_rejected(bad: float) -> None:
    with pytest.raises(QuantInputError):
        validate_price_series(_series([100.0, bad, 102.0]))
