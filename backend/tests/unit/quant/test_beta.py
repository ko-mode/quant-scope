"""CAPM beta: synthetic series where the slope is analytically obvious."""

from __future__ import annotations

import pandas as pd
import pytest

from quantscope.quant.results import InsufficientObservations, UndefinedResult
from quantscope.quant.risk import BetaResult, capm_beta

_PATTERN = [0.01, -0.02, 0.015, -0.005, 0.02]


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2023-01-02", periods=n)


def _bench(n: int) -> pd.Series:
    values = (_PATTERN * (n // len(_PATTERN) + 1))[:n]
    return pd.Series(values, index=_dates(n), dtype="float64")


@pytest.mark.parametrize("factor", [2.0, 0.5, -1.0])
def test_exact_linear_relationship(factor: float) -> None:
    bench = _bench(130)
    asset = bench * factor
    out = capm_beta(asset, bench)
    assert isinstance(out, BetaResult)
    assert out.beta == pytest.approx(factor, abs=1e-12)
    assert out.alpha_daily == pytest.approx(0.0, abs=1e-12)
    assert out.observations_used == 130
    assert out.r_squared == pytest.approx(1.0, abs=1e-9)


def test_constant_asset_excess_returns_leave_beta_valid_but_r_squared_none() -> None:
    # Asset excess return is constant while the benchmark varies: OLS still
    # yields beta = 0 and alpha = the constant, but R^2 = 1 - SS_res / SS_tot
    # is 0 / 0 (undefined), so it is reported as None - not 0.0, and not
    # UndefinedResult (the regression itself is fine).
    bench = _bench(130)
    asset = pd.Series(0.0, index=_dates(130))
    out = capm_beta(asset, bench)
    assert isinstance(out, BetaResult)
    assert out.beta == pytest.approx(0.0, abs=1e-12)
    assert out.alpha_daily == pytest.approx(0.0, abs=1e-12)
    assert out.r_squared is None
    assert out.observations_used == 130


def test_inner_join_on_trading_dates() -> None:
    master = _bench(140)
    asset = (master * 2.0).iloc[0:135]  # dates 0..134
    bench = master.iloc[5:140]  # dates 5..139
    out = capm_beta(asset, bench)
    assert isinstance(out, BetaResult)
    assert out.observations_used == 130  # overlap dates 5..134
    assert out.aligned_start == master.index[5]
    assert out.aligned_end == master.index[134]
    assert out.beta == pytest.approx(2.0, abs=1e-12)


def test_zero_daily_risk_free_series_leaves_beta_unchanged() -> None:
    bench = _bench(130)
    asset = bench * 2.0
    rf = pd.Series(0.0, index=_dates(130))
    out = capm_beta(asset, bench, rf)
    assert isinstance(out, BetaResult)
    assert out.beta == pytest.approx(2.0, abs=1e-12)
    assert out.observations_used == 130


def test_risk_free_series_restricts_the_window() -> None:
    bench = _bench(130)
    asset = bench * 2.0
    rf = pd.Series(0.0, index=_dates(125))
    out = capm_beta(asset, bench, rf)
    assert out == InsufficientObservations("capm_beta", 126, 125)


def test_zero_variance_benchmark_is_undefined() -> None:
    bench = pd.Series(0.005, index=_dates(130))
    asset = _bench(130)
    out = capm_beta(asset, bench)
    assert out == UndefinedResult("capm_beta", "benchmark excess return has zero variance", 130)


def test_below_gate_is_suppressed() -> None:
    bench = _bench(125)
    out = capm_beta(bench * 2.0, bench)
    assert out == InsufficientObservations("capm_beta", 126, 125)
