"""Annualised Sharpe ratio: closed-form value, RF handling, zero-variance guard."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from quantscope.quant.performance import SharpeResult, sharpe_ratio
from quantscope.quant.results import InsufficientObservations, QuantInputError, UndefinedResult


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2023-01-02", periods=n)


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=_dates(len(values)), dtype="float64")


def _spike(n: int) -> pd.Series:
    """n-1 zero returns then a single +0.10 move: sigma = a / sqrt(n)."""
    return _series([0.0] * (n - 1) + [0.1])


def test_closed_form_sharpe_with_zero_risk_free() -> None:
    out = sharpe_ratio(_spike(126))
    assert isinstance(out, SharpeResult)
    # SR = (a/n) / (a/sqrt(n)) * sqrt(252) = sqrt(252 / 126) = sqrt(2)
    assert out.sharpe_ratio == pytest.approx(math.sqrt(2.0))
    assert out.mean_daily_excess_return == pytest.approx(0.1 / 126)
    assert out.daily_excess_volatility == pytest.approx(0.1 / math.sqrt(126))
    assert out.observations_used == 126
    assert out.trading_days_per_year == 252
    assert out.risk_free_basis == "zero"


def test_annual_scalar_risk_free_is_compounded_not_divided() -> None:
    out = sharpe_ratio(_spike(126), annual_risk_free=0.0252)
    assert isinstance(out, SharpeResult)
    daily_compounded = (1.0 + 0.0252) ** (1.0 / 252) - 1.0
    assert out.mean_daily_excess_return == pytest.approx(0.1 / 126 - daily_compounded)
    # the naive annual/252 conversion would land elsewhere
    assert out.mean_daily_excess_return != pytest.approx(0.1 / 126 - 0.0252 / 252, rel=1e-6)
    assert out.risk_free_basis == "annual_scalar_compounded"


def test_zero_daily_risk_free_series_matches_the_zero_basis() -> None:
    out = sharpe_ratio(_spike(126), risk_free_daily=pd.Series(0.0, index=_dates(126)))
    assert isinstance(out, SharpeResult)
    assert out.sharpe_ratio == pytest.approx(math.sqrt(2.0))
    assert out.risk_free_basis == "daily_series"


def test_daily_risk_free_series_restricts_the_window() -> None:
    out = sharpe_ratio(_spike(126), risk_free_daily=pd.Series(0.0, index=_dates(125)))
    assert out == InsufficientObservations("sharpe_ratio", 126, 125)


def test_both_risk_free_inputs_rejected() -> None:
    with pytest.raises(QuantInputError, match="at most one"):
        sharpe_ratio(
            _spike(126), risk_free_daily=pd.Series(0.0, index=_dates(126)), annual_risk_free=0.02
        )


def test_annual_risk_free_at_or_below_minus_one_rejected() -> None:
    with pytest.raises(QuantInputError, match="greater than -1"):
        sharpe_ratio(_spike(126), annual_risk_free=-1.0)


def test_zero_excess_variance_is_undefined() -> None:
    out = sharpe_ratio(_series([0.005] * 130))
    assert out == UndefinedResult("sharpe_ratio", "zero excess-return variance", 130)


def test_below_gate_is_suppressed() -> None:
    out = sharpe_ratio(_spike(125))
    assert out == InsufficientObservations("sharpe_ratio", 126, 125)
