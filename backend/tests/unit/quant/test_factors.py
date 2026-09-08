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
import math

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
from scipy import stats as scipy_stats

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


# --------------------------------------------------------------------------- #
# HAC golden-reference test (test-quality gap; independence tightened RA-04):
# an independent NumPy Newey-West / Bartlett-kernel implementation, built from
# the published formula alone - never by calling statsmodels, never by
# calling quantscope.quant.factors.newey_west_lags, and never by reading
# production's own out.hac_lags - verifies the production HAC standard
# errors, t-stats, p-values and CI (both models) against a reference that
# owes production nothing but its inputs.
#
# Formula (Newey & West 1987, Bartlett kernel, statsmodels' `use_correction`
# small-sample adjustment - the exact configuration `_fit` uses):
#
#   beta_hat = (X'X)^-1 X'y                              (OLS, via lstsq)
#   u_t = y_t - x_t'beta_hat                              (residuals)
#   S = sum_t u_t^2 (x_t x_t')
#       + sum_{l=1}^{L} w_l sum_{t=l+1}^n u_t u_{t-l} (x_t x_{t-l}' + x_{t-l} x_t')
#       where w_l = 1 - l/(L+1)                           (Bartlett kernel)
#   S *= n / (n - k)                                      (use_correction=True)
#   Cov(beta_hat) = (X'X)^-1 S (X'X)^-1
#
# The Newey-West lag count L is *independently reproduced* here from the
# locked formula's own published text - max(1, floor(4*(T/100)**(2/9))) - not
# imported, not read off `out.hac_lags`. `out.hac_lags == _reference_lags(n)`
# is itself one of the assertions below, so a production regression in either
# the formula or the lag actually used would be caught, rather than the test
# silently re-deriving its expectation from whatever production just did.
# --------------------------------------------------------------------------- #
def _reference_newey_west_lags(observations_used: int) -> int:
    """Independent restatement of the locked Newey & West (1994) plug-in
    bandwidth - deliberately duplicated from the formula text, not imported
    from :func:`quantscope.quant.factors.newey_west_lags`, so this reference
    cannot silently inherit a bug from the function it is meant to check."""
    plugin_bandwidth: float = 4.0 * (observations_used / 100.0) ** (2.0 / 9.0)
    return max(1, math.floor(plugin_bandwidth))


def _hand_rolled_hac_ols(
    y: np.ndarray, design: np.ndarray, *, lags: int
) -> tuple[np.ndarray, np.ndarray]:
    """Independent reference: OLS coefficients and their Newey-West/Bartlett
    HAC covariance matrix, from the formula alone - no statsmodels, no
    quantscope.quant.factors. Returns (coefficients, covariance_matrix)."""
    n, k = design.shape
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    resid = y - design @ beta
    xtx_inv = np.linalg.inv(design.T @ design)

    meat = np.zeros((k, k))
    for t in range(n):
        xt = design[t]
        meat += resid[t] ** 2 * np.outer(xt, xt)
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1)
        gamma = np.zeros((k, k))
        for t in range(lag, n):
            xt, xtl = design[t], design[t - lag]
            gamma += resid[t] * resid[t - lag] * (np.outer(xt, xtl) + np.outer(xtl, xt))
        meat += weight * gamma
    meat *= n / (n - k)  # use_correction=True small-sample adjustment

    cov = xtx_inv @ meat @ xtx_inv
    return beta, cov


def test_capm_regression_hac_matches_independent_newey_west_reference() -> None:
    # A fixed, deterministic (seeded) dataset with AR(1)-autocorrelated
    # residuals, so HAC and classical OLS standard errors meaningfully
    # differ - a purely i.i.d.-noise fixture would not actually exercise the
    # Bartlett-kernel weighting this test is meant to catch a regression in.
    rng = np.random.default_rng(20260907)
    n = 130
    spy_excess = rng.normal(0.0, 0.01, n)
    innovations = rng.normal(0.0, 0.008, n)
    residual = np.zeros(n)
    residual[0] = innovations[0]
    for t in range(1, n):
        residual[t] = 0.6 * residual[t - 1] + innovations[t]
    alpha_true, beta_true = 0.0003, 0.9
    asset_excess = alpha_true + beta_true * spy_excess + residual

    # RA-04: a deterministic, non-zero, *varying* daily RF series - not the
    # zero series used before. capm_regression must independently reconstruct
    # `asset_excess`/`spy_excess` by subtracting this exact series from the
    # raw asset/SPY returns it is handed; feeding it a non-trivial RF and
    # comparing against a reference built from the true, pre-RF excess values
    # actually exercises that subtraction rather than assuming it away.
    rf_values = 0.00006 + 0.00002 * rng.standard_normal(n)

    dates = _dates(n)
    asset_returns = pd.Series(asset_excess + rf_values, index=dates)  # raw total return
    spy_returns = pd.Series(spy_excess + rf_values, index=dates)  # raw total return
    rf = pd.Series(rf_values, index=dates)

    out = capm_regression(asset_returns, spy_returns, rf)
    assert isinstance(out, FactorRegressionResult)

    reference_lags = _reference_newey_west_lags(n)
    design = np.column_stack([np.ones(n), spy_excess])
    ref_beta, ref_cov = _hand_rolled_hac_ols(asset_excess, design, lags=reference_lags)
    ref_se = np.sqrt(np.diag(ref_cov))
    ref_t = ref_beta / ref_se
    # HAC/robust covariance results use asymptotic normal inference
    # (statsmodels' `use_t=False` for cov_type="HAC"), not the exact
    # finite-sample t-distribution - HAC's own justification is asymptotic.
    ref_p = 2.0 * scipy_stats.norm.sf(np.abs(ref_t))
    ref_ci_low = ref_beta - scipy_stats.norm.ppf(0.975) * ref_se
    ref_ci_high = ref_beta + scipy_stats.norm.ppf(0.975) * ref_se

    assert out.hac_lags == reference_lags
    for i, coef in enumerate(out.coefficients):
        assert coef.estimate == pytest.approx(ref_beta[i], rel=1e-9)
        assert coef.std_error == pytest.approx(ref_se[i], rel=1e-6)
        assert coef.t_stat == pytest.approx(ref_t[i], rel=1e-6)
        assert coef.p_value == pytest.approx(ref_p[i], rel=1e-4, abs=1e-12)
        assert coef.ci_low == pytest.approx(ref_ci_low[i], rel=1e-6)
        assert coef.ci_high == pytest.approx(ref_ci_high[i], rel=1e-6)


def test_ff3_regression_hac_matches_independent_newey_west_reference() -> None:
    # Same independent-reference doctrine, for the 4-coefficient FF3 design
    # matrix (intercept + 3 factors), confirming the reference generalises
    # beyond the single-regressor CAPM case.
    rng = np.random.default_rng(20260907)
    n = 260
    mkt = rng.normal(0.0, 0.01, n)
    smb = rng.normal(0.0, 0.006, n)
    hml = rng.normal(0.0, 0.005, n)
    innovations = rng.normal(0.0, 0.007, n)
    residual = np.zeros(n)
    residual[0] = innovations[0]
    for t in range(1, n):
        residual[t] = 0.5 * residual[t - 1] + innovations[t]
    alpha_true, b_mkt, b_smb, b_hml = -0.0001, 1.05, 0.3, -0.2
    asset_excess = alpha_true + b_mkt * mkt + b_smb * smb + b_hml * hml + residual

    # RA-04: deterministic, non-zero, varying daily RF, exactly as for CAPM
    # above - ff3_regression only subtracts RF from the asset's own return
    # (the Mkt-RF/SMB/HML factors are already excess/factor returns and are
    # used as-is); feeding a raw total-return asset series here exercises
    # that one subtraction rather than assuming it away with RF = 0.
    rf_values = 0.00004 + 0.000015 * rng.standard_normal(n)

    dates = _dates(n)
    asset_returns = pd.Series(asset_excess + rf_values, index=dates)  # raw total return
    rf = pd.Series(rf_values, index=dates)
    out = ff3_regression(
        asset_returns,
        pd.Series(mkt, index=dates),
        pd.Series(smb, index=dates),
        pd.Series(hml, index=dates),
        rf,
    )
    assert isinstance(out, FactorRegressionResult)

    reference_lags = _reference_newey_west_lags(n)
    design = np.column_stack([np.ones(n), mkt, smb, hml])
    ref_beta, ref_cov = _hand_rolled_hac_ols(asset_excess, design, lags=reference_lags)
    ref_se = np.sqrt(np.diag(ref_cov))
    ref_t = ref_beta / ref_se
    # Asymptotic normal inference, matching HAC's own use_t=False convention.
    ref_p = 2.0 * scipy_stats.norm.sf(np.abs(ref_t))
    ref_ci_low = ref_beta - scipy_stats.norm.ppf(0.975) * ref_se
    ref_ci_high = ref_beta + scipy_stats.norm.ppf(0.975) * ref_se

    assert out.hac_lags == reference_lags
    for i, coef in enumerate(out.coefficients):
        assert coef.estimate == pytest.approx(ref_beta[i], rel=1e-9)
        assert coef.std_error == pytest.approx(ref_se[i], rel=1e-6)
        assert coef.t_stat == pytest.approx(ref_t[i], rel=1e-6)
        assert coef.p_value == pytest.approx(ref_p[i], rel=1e-4, abs=1e-12)
        assert coef.ci_low == pytest.approx(ref_ci_low[i], rel=1e-6)
        assert coef.ci_high == pytest.approx(ref_ci_high[i], rel=1e-6)
