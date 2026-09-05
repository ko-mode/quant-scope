"""CAPM regression (SPY-based) and Fama-French 3-factor regression: synthetic
series with known coefficients, one-common-panel alignment, and the explicit
pre-fit variance/rank checks (ADR 0017 addendum, Phase 3B).

Golden values for the exact-linear cases are the constructed true coefficients
themselves, not a second, independent computation - matching this package's
existing doctrine (``test_beta.py``, ``test_comparison.py``) of hand-derived,
not implementation-derived, expectations.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from quantscope.quant.factors import (
    FactorRegressionResult,
    RegressionCoefficient,
    _finite_or_none,
    capm_regression,
    ff3_regression,
    newey_west_lags,
)
from quantscope.quant.results import InsufficientObservations, QuantInputError, UndefinedResult

_PATTERN = [0.01, -0.02, 0.015, -0.005, 0.02]


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2023-01-02", periods=n)


def _tiled(pattern: list[float], n: int) -> np.ndarray:
    return np.array((pattern * (n // len(pattern) + 1))[:n], dtype="float64")


def _series(values: np.ndarray, n: int) -> pd.Series:
    return pd.Series(values, index=_dates(n), dtype="float64")


def _zero_rf(n: int) -> pd.Series:
    return pd.Series(0.0, index=_dates(n), dtype="float64")


# --------------------------------------------------------------------------- #
# Newey-West lag formula
# --------------------------------------------------------------------------- #
def test_newey_west_lag_formula_matches_hand_computation() -> None:
    # floor(4 * (T/100) ** (2/9)), minimum 1 - values hand-computed independently.
    assert newey_west_lags(1) == 1
    assert newey_west_lags(10) == 2
    assert newey_west_lags(60) == 3
    assert newey_west_lags(100) == 4
    assert newey_west_lags(126) == 4  # CAPM regression gate
    assert newey_west_lags(250) == 4  # FF3 regression gate
    assert newey_west_lags(300) == 5
    assert newey_west_lags(1000) == 6


# --------------------------------------------------------------------------- #
# _finite_or_none - the NaN/Infinity -> None guard
# --------------------------------------------------------------------------- #
def test_finite_or_none() -> None:
    assert _finite_or_none(1.5) == 1.5
    assert _finite_or_none(0.0) == 0.0
    assert _finite_or_none(float("nan")) is None
    assert _finite_or_none(float("inf")) is None
    assert _finite_or_none(float("-inf")) is None


# --------------------------------------------------------------------------- #
# CAPM regression: exact linear relationship
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("alpha_true", "beta_true"), [(0.0, 2.0), (0.0003, 1.8), (-0.0002, 0.5)])
def test_capm_regression_recovers_known_coefficients(alpha_true: float, beta_true: float) -> None:
    n = 130
    spy = _series(_tiled(_PATTERN, n), n)
    rf = _zero_rf(n)
    asset = pd.Series(alpha_true + beta_true * spy.to_numpy(), index=spy.index)

    out = capm_regression(asset, spy, rf)
    assert isinstance(out, FactorRegressionResult)
    assert out.model == "capm_regression"
    assert out.observations_used == n
    assert out.coefficients[0].name == "alpha"
    assert out.coefficients[0].estimate == pytest.approx(alpha_true, abs=1e-8)
    assert out.coefficients[1].name == "spy_excess"
    assert out.coefficients[1].estimate == pytest.approx(beta_true, abs=1e-8)
    assert out.r_squared == pytest.approx(1.0, abs=1e-6)
    assert out.adjusted_r_squared == pytest.approx(1.0, abs=1e-6)
    assert out.hac_lags == newey_west_lags(n)
    # A near-perfect fit still yields finite (if extreme) inference, not None.
    for coef in out.coefficients:
        assert coef.std_error is not None
        assert coef.t_stat is not None
        assert coef.p_value is not None


def test_capm_regression_one_fitted_model_not_two(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exactly one ``statsmodels`` fit is performed, with HAC covariance - the
    same fit supplies both the OLS coefficients and the HAC inference."""
    calls: list[dict[str, object]] = []
    original_fit = sm.OLS.fit

    def spy_fit(self: sm.OLS, *args: object, **kwargs: object) -> object:
        calls.append(dict(kwargs))
        return original_fit(self, *args, **kwargs)

    monkeypatch.setattr(sm.OLS, "fit", spy_fit)

    n = 130
    spy = _series(_tiled(_PATTERN, n), n)
    rf = _zero_rf(n)
    asset = spy * 1.5
    out = capm_regression(asset, spy, rf)

    assert isinstance(out, FactorRegressionResult)
    assert len(calls) == 1
    assert calls[0]["cov_type"] == "HAC"
    assert calls[0]["cov_kwds"] == {"maxlags": newey_west_lags(n), "use_correction": True}


def test_capm_regression_below_gate_is_insufficient() -> None:
    n = 125
    spy = _series(_tiled(_PATTERN, n), n)
    rf = _zero_rf(n)
    out = capm_regression(spy * 2.0, spy, rf)
    assert out == InsufficientObservations("capm_regression", 126, 125)


def test_capm_regression_constant_spy_excess_is_undefined() -> None:
    n = 130
    spy = pd.Series(0.005, index=_dates(n))
    rf = _zero_rf(n)
    asset = _series(_tiled(_PATTERN, n), n)
    out = capm_regression(asset, spy, rf)
    assert out == UndefinedResult("capm_regression", "regressor 'spy_excess' has zero variance", n)


def test_capm_regression_constant_asset_excess_is_ok_with_none_r_squared() -> None:
    # Mirrors the existing `capm_beta` precedent: a constant dependent variable
    # leaves the regression well defined (beta -> 0, alpha -> the constant) but
    # R^2 = 1 - SS_res/SS_tot is 0/0, reported as None, never 0.0.
    n = 130
    spy = _series(_tiled(_PATTERN, n), n)
    rf = _zero_rf(n)
    asset = pd.Series(0.0, index=_dates(n))
    out = capm_regression(asset, spy, rf)
    assert isinstance(out, FactorRegressionResult)
    assert out.coefficients[1].estimate == pytest.approx(0.0, abs=1e-8)
    assert out.r_squared is None
    assert out.adjusted_r_squared is None


def test_capm_regression_inner_join_restricts_the_window() -> None:
    master = _series(_tiled(_PATTERN, 300), 300)
    spy = master.iloc[0:280]
    asset = (master * 1.5).iloc[10:300]
    rf = _zero_rf(300).iloc[5:295]
    out = capm_regression(asset, spy, rf)
    assert isinstance(out, FactorRegressionResult)
    # Common window: asset[10:300) ^ spy[0:280) ^ rf[5:295) = [10:280) -> 270 obs
    assert out.observations_used == 270
    assert out.aligned_start == master.index[10]
    assert out.aligned_end == master.index[279]


# --------------------------------------------------------------------------- #
# FF3 regression: exact linear relationship
# --------------------------------------------------------------------------- #
def _ff3_factors(n: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    mkt = _series(_tiled(_PATTERN, n), n)
    smb = _series(_tiled([0.004, -0.002, 0.001, -0.003, 0.0025], n), n)
    hml = _series(_tiled([-0.001, 0.002, -0.0015, 0.0005, 0.001], n), n)
    return mkt, smb, hml


def test_ff3_regression_recovers_known_coefficients() -> None:
    n = 260
    mkt, smb, hml = _ff3_factors(n)
    rf = _zero_rf(n)
    alpha_true, beta_mkt, beta_smb, beta_hml = 0.0001, 1.1, 0.4, -0.3
    asset = pd.Series(
        alpha_true
        + beta_mkt * mkt.to_numpy()
        + beta_smb * smb.to_numpy()
        + beta_hml * hml.to_numpy(),
        index=mkt.index,
    )

    out = ff3_regression(asset, mkt, smb, hml, rf)
    assert isinstance(out, FactorRegressionResult)
    assert out.model == "ff3_regression"
    assert [c.name for c in out.coefficients] == ["alpha", "mkt_rf", "smb", "hml"]
    estimates = {c.name: c.estimate for c in out.coefficients}
    assert estimates["alpha"] == pytest.approx(alpha_true, abs=1e-8)
    assert estimates["mkt_rf"] == pytest.approx(beta_mkt, abs=1e-8)
    assert estimates["smb"] == pytest.approx(beta_smb, abs=1e-8)
    assert estimates["hml"] == pytest.approx(beta_hml, abs=1e-8)
    assert out.r_squared == pytest.approx(1.0, abs=1e-6)
    assert out.hac_lags == newey_west_lags(n)


def test_ff3_regression_noisy_fixture_recovers_approximate_coefficients() -> None:
    n = 260
    mkt, smb, hml = _ff3_factors(n)
    rf = _zero_rf(n)
    rng = np.random.default_rng(20260905)
    noise = rng.normal(0.0, 0.0015, n)
    alpha_true, beta_mkt, beta_smb, beta_hml = 0.0002, 0.9, -0.2, 0.5
    asset = pd.Series(
        alpha_true
        + beta_mkt * mkt.to_numpy()
        + beta_smb * smb.to_numpy()
        + beta_hml * hml.to_numpy()
        + noise,
        index=mkt.index,
    )

    out = ff3_regression(asset, mkt, smb, hml, rf)
    assert isinstance(out, FactorRegressionResult)
    estimates = {c.name: c.estimate for c in out.coefficients}
    assert estimates["mkt_rf"] == pytest.approx(beta_mkt, abs=0.1)
    assert estimates["smb"] == pytest.approx(beta_smb, abs=0.15)
    assert estimates["hml"] == pytest.approx(beta_hml, abs=0.15)
    r_squared = out.r_squared
    assert r_squared is not None and 0.0 < r_squared < 1.0
    for coef in out.coefficients:
        assert coef.std_error is not None and coef.std_error > 0
        assert coef.t_stat is not None
        assert coef.p_value is not None
        ci_low, ci_high = coef.ci_low, coef.ci_high
        assert ci_low is not None and ci_high is not None
        assert ci_low <= coef.estimate <= ci_high


def test_ff3_regression_below_gate_is_insufficient() -> None:
    n = 249
    mkt, smb, hml = _ff3_factors(n)
    rf = _zero_rf(n)
    out = ff3_regression(mkt * 1.0, mkt, smb, hml, rf)
    assert out == InsufficientObservations("ff3_regression", 250, 249)


def test_ff3_regression_constant_factor_is_undefined_naming_that_regressor() -> None:
    n = 260
    mkt, smb, hml = _ff3_factors(n)
    smb_constant = pd.Series(0.0, index=mkt.index)
    rf = _zero_rf(n)
    asset = pd.Series(0.0001 + 0.8 * mkt.to_numpy() + 0.3 * hml.to_numpy(), index=mkt.index)
    out = ff3_regression(asset, mkt, smb_constant, hml, rf)
    assert out == UndefinedResult("ff3_regression", "regressor 'smb' has zero variance", n)


def test_ff3_regression_rank_deficient_design_is_undefined() -> None:
    # hml is an exact linear function of smb - both individually vary (so the
    # per-regressor variance check passes), but the assembled design matrix is
    # singular. The variance check must not mask this: a *different*, generic
    # reason is expected.
    n = 260
    mkt, smb, _hml = _ff3_factors(n)
    hml_collinear = smb * 2.0
    rf = _zero_rf(n)
    asset = pd.Series(0.0001 + 0.8 * mkt.to_numpy() + 0.3 * smb.to_numpy(), index=mkt.index)
    out = ff3_regression(asset, mkt, smb, hml_collinear, rf)
    assert out == UndefinedResult("ff3_regression", "design matrix is rank-deficient", n)


def test_ff3_regression_one_common_panel_alignment() -> None:
    # Ragged windows for every one of the five series - only the true 5-way
    # intersection may be used, never a pairwise one.
    master_index = _dates(300)
    mkt = pd.Series(_tiled(_PATTERN, 300), index=master_index).iloc[0:290]
    smb = pd.Series(_tiled([0.004, -0.002, 0.001, -0.003, 0.0025], 300), index=master_index).iloc[
        5:300
    ]
    hml = pd.Series(_tiled([-0.001, 0.002, -0.0015, 0.0005, 0.001], 300), index=master_index).iloc[
        3:295
    ]
    rf = pd.Series(0.0, index=master_index).iloc[8:298]
    asset = pd.Series(
        0.0001 + 0.5 * mkt.reindex(master_index).ffill().bfill().to_numpy()[:300],
        index=master_index,
    ).iloc[2:296]

    out = ff3_regression(asset, mkt, smb, hml, rf)
    assert isinstance(out, FactorRegressionResult)
    # Intersection of [2,296) & [0,290) & [5,300) & [3,295) & [8,298) = [8,290)
    assert out.observations_used == 282
    assert out.aligned_start == master_index[8]
    assert out.aligned_end == master_index[289]


# --------------------------------------------------------------------------- #
# Malformed input reuses frames.py validation (raised, not returned)
# --------------------------------------------------------------------------- #
def test_capm_regression_unsorted_dates_raises() -> None:
    n = 130
    spy = _series(_tiled(_PATTERN, n), n)
    rf = _zero_rf(n)
    shuffled = spy.iloc[::-1]
    with pytest.raises(QuantInputError):
        capm_regression(shuffled, spy, rf)


def test_ff3_regression_empty_series_raises() -> None:
    empty = pd.Series([], dtype="float64", index=pd.DatetimeIndex([]))
    n = 260
    mkt, smb, hml = _ff3_factors(n)
    rf = _zero_rf(n)
    with pytest.raises(QuantInputError):
        ff3_regression(empty, mkt, smb, hml, rf)


# --------------------------------------------------------------------------- #
# No alpha_annualized field anywhere on the result dataclass
# --------------------------------------------------------------------------- #
def test_factor_regression_result_has_no_alpha_annualized_field() -> None:
    field_names = {f.name for f in dataclasses.fields(FactorRegressionResult)}
    assert "alpha_annualized" not in field_names
    assert field_names == {
        "model",
        "observations_used",
        "aligned_start",
        "aligned_end",
        "coefficients",
        "r_squared",
        "adjusted_r_squared",
        "hac_lags",
    }


def test_regression_coefficient_field_shape() -> None:
    field_names = {f.name for f in dataclasses.fields(RegressionCoefficient)}
    assert field_names == {
        "name",
        "estimate",
        "std_error",
        "t_stat",
        "p_value",
        "ci_low",
        "ci_high",
    }
