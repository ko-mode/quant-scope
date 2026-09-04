"""Annualised volatility: ddof=1 daily sigma, sqrt(252) annualisation."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from quantscope.quant.results import InsufficientObservations
from quantscope.quant.risk import VolatilityResult, annualised_volatility


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2023-01-02", periods=n)


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=_dates(len(values)), dtype="float64")


def test_constant_returns_have_zero_volatility() -> None:
    out = annualised_volatility(_series([0.005] * 80))
    assert isinstance(out, VolatilityResult)
    # exactly zero to within floating-point precision (0.005 is not representable)
    assert out.daily_volatility == pytest.approx(0.0)
    assert out.annualised_volatility == pytest.approx(0.0)
    assert out.observations_used == 80
    assert out.trading_days_per_year == 252


def test_known_closed_form_volatility() -> None:
    # 59 zeros + one +0.10 move (n = 60): sample sigma = a / sqrt(n).
    out = annualised_volatility(_series([0.0] * 59 + [0.1]))
    assert isinstance(out, VolatilityResult)
    daily = 0.1 / math.sqrt(60)
    assert out.daily_volatility == pytest.approx(daily)
    assert out.annualised_volatility == pytest.approx(daily * math.sqrt(252))


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (59, InsufficientObservations("annualised_volatility", 60, 59)),
        (60, None),
    ],
)
def test_observation_gate(n: int, expected: object) -> None:
    out = annualised_volatility(_series([0.01, -0.01] * (n // 2) + [0.01] * (n % 2)))
    if expected is None:
        assert isinstance(out, VolatilityResult)
        assert out.observations_used == 60
    else:
        assert out == expected
