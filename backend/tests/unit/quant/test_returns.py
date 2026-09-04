"""Simple returns, cumulative wealth index and descriptive return stats.

Golden values are computed by hand from the definitions in ADR 0017, not from
the implementation.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from quantscope.quant.results import InsufficientObservations, QuantInputError
from quantscope.quant.returns import (
    ReturnSummary,
    cumulative_wealth_index,
    return_summary,
    simple_returns,
)


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2023-01-02", periods=n)


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=_dates(len(values)), dtype="float64")


def test_simple_returns_hand_example() -> None:
    prices = _series([100.0, 110.0, 99.0])
    out = simple_returns(prices)
    # 110/100 - 1 = 0.10 ; 99/110 - 1 = -0.10
    assert list(out.round(10)) == [0.10, -0.10]
    assert list(out.index) == list(prices.index[1:])
    assert out.name == "return"


def test_simple_returns_needs_two_prices() -> None:
    with pytest.raises(QuantInputError, match="two prices"):
        simple_returns(_series([100.0]))


def test_cumulative_wealth_index_compounds() -> None:
    out = cumulative_wealth_index(_series([0.1, -0.1, 0.05]))
    # 1.1 ; 1.1*0.9 = 0.99 ; 0.99*1.05 = 1.0395
    assert list(out.round(10)) == [1.1, 0.99, 1.0395]
    assert out.name == "wealth_index"


def test_return_summary_below_gate_is_suppressed() -> None:
    out = return_summary(_series([0.0] * 59))
    assert out == InsufficientObservations("return_summary", 60, 59)


def test_return_summary_at_gate() -> None:
    # 59 zeros then a single +0.10 move: closed-form stats (n = 60).
    out = return_summary(_series([0.0] * 59 + [0.1]))
    assert isinstance(out, ReturnSummary)
    assert out.observations_used == 60
    assert out.mean_daily_return == pytest.approx(0.1 / 60)
    assert out.stdev_daily_return == pytest.approx(0.1 / math.sqrt(60))
    assert out.cumulative_return == pytest.approx(0.10)
    assert out.min_daily_return == 0.0
    assert out.max_daily_return == pytest.approx(0.10)
