"""1-day historical VaR / ES: lower empirical quantile, `<=` tail, positive loss."""

from __future__ import annotations

import pandas as pd
import pytest

from quantscope.quant.results import InsufficientObservations, QuantInputError
from quantscope.quant.risk import HistoricalVarEsResult, historical_var_es


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2023-01-02", periods=n)


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=_dates(len(values)), dtype="float64")


def _ladder(n: int) -> pd.Series:
    # Distinct, ascending: -0.0100, -0.0099, ... (step 0.0001).
    return _series([(-100 + i) / 10000 for i in range(n)])


def test_var_es_95_is_a_known_order_statistic() -> None:
    out = historical_var_es(_ladder(200), 0.95)
    assert isinstance(out, HistoricalVarEsResult)
    # lower quantile at q = 0.05, n = 200 -> index floor(0.05 * 199) = 9 -> -0.0091
    assert out.threshold_return == pytest.approx(-0.0091)
    assert out.var == pytest.approx(0.0091)
    # tail = values[0..9]; mean of (-100..-91)/10000 = -0.00955
    assert out.tail_observations == 10
    assert out.expected_shortfall == pytest.approx(0.00955)
    assert out.observations_used == 200
    assert out.horizon_days == 1
    assert out.method == "historical_lower_quantile"
    assert out.confidence == 0.95


def test_var_es_99_tail() -> None:
    out = historical_var_es(_ladder(200), 0.99)
    assert isinstance(out, HistoricalVarEsResult)
    # index floor(0.01 * 199) = 1 -> -0.0099
    assert out.threshold_return == pytest.approx(-0.0099)
    assert out.var == pytest.approx(0.0099)
    assert out.tail_observations == 2
    assert out.expected_shortfall == pytest.approx(0.00995)


def test_ties_at_the_threshold_are_deterministic() -> None:
    returns = _series([-0.02] * 10 + [-0.01] * 10 + [0.0] * 110)  # n = 130
    out95 = historical_var_es(returns, 0.95)
    assert isinstance(out95, HistoricalVarEsResult)
    # floor(0.05 * 129) = 6 -> -0.02 ; tail is every r <= -0.02
    assert out95.threshold_return == pytest.approx(-0.02)
    assert out95.tail_observations == 10
    assert out95.expected_shortfall == pytest.approx(0.02)

    out90 = historical_var_es(returns, 0.90)
    assert isinstance(out90, HistoricalVarEsResult)
    # floor(0.10 * 129) = 12 -> -0.01 ; tail includes the -0.02 and -0.01 blocks
    assert out90.threshold_return == pytest.approx(-0.01)
    assert out90.tail_observations == 20
    assert out90.expected_shortfall == pytest.approx(0.015)


def test_constant_returns_give_a_negative_var_not_a_fabricated_zero() -> None:
    out = historical_var_es(_series([0.001] * 130), 0.95)
    assert isinstance(out, HistoricalVarEsResult)
    assert out.threshold_return == pytest.approx(0.001)
    assert out.var == pytest.approx(-0.001)
    assert out.expected_shortfall == pytest.approx(-0.001)
    assert out.tail_observations == 130


@pytest.mark.parametrize("confidence", [0.0, 1.0, 1.5, -0.1])
def test_confidence_out_of_range_rejected(confidence: float) -> None:
    with pytest.raises(QuantInputError, match="confidence must lie"):
        historical_var_es(_ladder(200), confidence)


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (125, InsufficientObservations("historical_var_es", 126, 125)),
        (126, None),
    ],
)
def test_observation_gate(n: int, expected: object) -> None:
    out = historical_var_es(_ladder(n), 0.95)
    if expected is None:
        assert isinstance(out, HistoricalVarEsResult)
        assert out.observations_used == 126
    else:
        assert out == expected
