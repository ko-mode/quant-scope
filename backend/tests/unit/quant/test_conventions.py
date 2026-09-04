"""The frozen numerical conventions match ADR 0017 exactly."""

from __future__ import annotations

from quantscope.quant import conventions as c


def test_annualisation_basis() -> None:
    assert c.TRADING_DAYS_PER_YEAR == 252
    assert c.STDDEV_DDOF == 1


def test_var_es_conventions() -> None:
    assert c.VAR_CONFIDENCE_LEVELS == (0.95, 0.99)
    assert c.VAR_ES_HORIZON_DAYS == 1


def test_observation_gates() -> None:
    assert c.MIN_OBS_RETURN_STATS == 60
    assert c.MIN_OBS_VOLATILITY == 60
    assert c.MIN_OBS_DRAWDOWN == 60
    assert c.MIN_OBS_SHARPE == 126
    assert c.MIN_OBS_BETA == 126
    assert c.MIN_OBS_HISTORICAL_VAR == 126
    assert c.MIN_OBS_HISTORICAL_ES == 126
    assert c.MIN_OBS_FF3_REGRESSION == 250


def test_observation_lookup_table() -> None:
    assert c.MIN_OBSERVATIONS == {
        "return_summary": 60,
        "annualised_volatility": 60,
        "drawdown": 60,
        "sharpe_ratio": 126,
        "capm_beta": 126,
        "historical_var_es": 126,
        "ff3_regression": 250,
    }
