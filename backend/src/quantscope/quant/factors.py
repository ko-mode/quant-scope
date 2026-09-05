"""CAPM regression (SPY-based) and Fama-French 3-factor regression, both with
Newey-West (HAC) inference (ADR 0009, ADR 0017 Phase 3B addendum).

Both regressions share one internal OLS+HAC fitting routine (:func:`_fit`);
they differ only in which regressor columns feed the design matrix. Neither
touches :mod:`quantscope.quant.risk` - ``capm_beta`` is unchanged and remains
the sole basis for the Risk & Return "Beta vs SPY" metric.

Conventions (ADR 0017 addendum, Phase 3B):

* **CAPM regression** - OLS of the security's daily excess return on SPY's
  daily excess return: the same economic model as
  :func:`quantscope.quant.risk.capm_beta`, but with full HAC inference
  (standard error, t-statistic, p-value, 95% CI) for alpha and the SPY beta,
  which ``capm_beta`` does not compute.
* **FF3 regression** - OLS of the security's daily excess return on Ken
  French Mkt-RF, SMB and HML. The FF3 Mkt-RF coefficient and the SPY CAPM
  beta are different quantities and must be labelled distinctly wherever both
  appear (ADR 0005, ADR 0009, ADR 0017).
* **One fitted OLS model, not two.** ``sm.OLS(y, X).fit(cov_type="HAC",
  cov_kwds={"maxlags": L})`` supplies both the coefficients (``cov_type``
  changes only how the covariance is estimated, never the point estimates)
  and the HAC-based inference from that same fit - there is no separate
  classical-OLS fit anywhere.
* **Newey-West lag**: :func:`newey_west_lags`, ``floor(4*(T/100)**(2/9))``,
  minimum 1 - a deterministic function of the sample size alone, recorded
  verbatim as ``hac_lags`` on every successful result.
* **HAC-only inference** is exposed (standard error, t-statistic, p-value, a
  95% confidence interval) - no parallel classical-OLS inference set.
* **Alpha is never annualised** - reported only as the daily regression
  intercept, exactly like ``capm_beta.alpha_daily``.
* **Explicit pre-fit checks**, in this order, never delegated to
  ``statsmodels.add_constant(..., has_constant="raise")``:

  1. Each regressor's own variance - a constant regressor is reported by
     name (``UndefinedResult(metric, "regressor '<name>' has zero variance",
     n)``).
  2. Only if every regressor varies: the assembled design matrix's rank -
     collinearity among otherwise-varying regressors is reported generically
     (``UndefinedResult(metric, "design matrix is rank-deficient", n)``).

  A constant *dependent* variable (the asset's excess return) is not an
  ``UndefinedResult`` - the regression is still well defined (matching the
  ``capm_beta`` precedent), only ``r_squared``/``adjusted_r_squared`` become
  ``None`` (statsmodels' own ``nan`` for a zero total sum of squares).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm

from quantscope.quant.conventions import MIN_OBS_CAPM_REGRESSION, MIN_OBS_FF3_REGRESSION
from quantscope.quant.frames import validate_return_series
from quantscope.quant.results import InsufficientObservations, UndefinedResult

_CONFIDENCE_LEVEL = 0.95


def newey_west_lags(observations_used: int) -> int:
    """Newey & West (1994) plug-in bandwidth: ``floor(4*(T/100)**(2/9))``, min 1.

    A deterministic function of the sample size alone - no data-dependent
    bandwidth search - so the lag used is always reproducible from
    ``observations_used`` and is echoed verbatim as ``hac_lags`` on every
    successful result.
    """
    return max(1, int((4.0 * (observations_used / 100.0) ** (2.0 / 9.0)) // 1))


@dataclass(frozen=True, slots=True)
class RegressionCoefficient:
    """One OLS coefficient with Newey-West (HAC) inference.

    ``estimate`` comes from the shared OLS fit and is always populated when
    the whole regression is estimable. The four inference fields are
    independently ``None`` when that one statistic is mathematically
    undefined for this coefficient (e.g. a HAC standard error of exactly
    zero makes the t-statistic undefined) - never ``0``, never ``nan``/``inf``.
    """

    name: str
    estimate: float
    std_error: float | None
    t_stat: float | None
    p_value: float | None
    ci_low: float | None
    ci_high: float | None


@dataclass(frozen=True, slots=True)
class FactorRegressionResult:
    """One estimable factor regression - a CAPM (SPY) or FF3 fit.

    ``coefficients[0]`` is always ``alpha`` (the daily intercept, never
    annualised); the remaining entries are the model's regressor loadings in
    a fixed order (``spy_excess`` for CAPM; ``mkt_rf``, ``smb``, ``hml`` for
    FF3).
    """

    model: str
    observations_used: int
    aligned_start: pd.Timestamp
    aligned_end: pd.Timestamp
    coefficients: tuple[RegressionCoefficient, ...]
    r_squared: float | None
    adjusted_r_squared: float | None
    hac_lags: int


def _finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _fit(
    frame: pd.DataFrame, *, y_col: str, regressor_names: list[str], model: str
) -> FactorRegressionResult | UndefinedResult:
    """Shared OLS+HAC fit given one already-aligned excess-return panel.

    ``frame`` must already be the one common aligned sample - this function
    performs no further alignment, only the pre-fit checks and the fit
    itself.
    """
    n = len(frame)
    for name in regressor_names:
        column = frame[name].to_numpy(dtype="float64")
        if column.min() == column.max():
            return UndefinedResult(model, f"regressor '{name}' has zero variance", n)

    design = np.column_stack(
        [np.ones(n), *(frame[name].to_numpy(dtype="float64") for name in regressor_names)]
    )
    if np.linalg.matrix_rank(design) < design.shape[1]:
        return UndefinedResult(model, "design matrix is rank-deficient", n)

    y = frame[y_col].to_numpy(dtype="float64")
    lags = newey_west_lags(n)
    fit = sm.OLS(y, design).fit(cov_type="HAC", cov_kwds={"maxlags": lags, "use_correction": True})

    coefficient_names = ["alpha", *regressor_names]
    conf_int = np.asarray(fit.conf_int(alpha=1.0 - _CONFIDENCE_LEVEL))
    coefficients = tuple(
        RegressionCoefficient(
            name=coefficient_names[i],
            estimate=float(fit.params[i]),
            std_error=_finite_or_none(float(fit.bse[i])),
            t_stat=_finite_or_none(float(fit.tvalues[i])),
            p_value=_finite_or_none(float(fit.pvalues[i])),
            ci_low=_finite_or_none(float(conf_int[i][0])),
            ci_high=_finite_or_none(float(conf_int[i][1])),
        )
        for i in range(len(coefficient_names))
    )

    return FactorRegressionResult(
        model=model,
        observations_used=n,
        aligned_start=pd.Timestamp(frame.index[0]),
        aligned_end=pd.Timestamp(frame.index[-1]),
        coefficients=coefficients,
        r_squared=_finite_or_none(float(fit.rsquared)),
        adjusted_r_squared=_finite_or_none(float(fit.rsquared_adj)),
        hac_lags=lags,
    )


def capm_regression(
    asset_returns: pd.Series,
    spy_returns: pd.Series,
    risk_free_daily: pd.Series,
) -> FactorRegressionResult | InsufficientObservations | UndefinedResult:
    """OLS of ``asset``'s daily excess return on SPY's daily excess return,
    with Newey-West (HAC) inference, over the one common inner-joined sample.

    ``(r_i - r_f) = alpha + beta_SPY * (r_SPY - r_f) + eps``. Same excess-
    return construction as :func:`quantscope.quant.risk.capm_beta`, which is
    unaffected by this function and remains the sole basis for the Risk &
    Return "Beta vs SPY" metric - this adds full inference for the identical
    model, for the Factors tab only.
    """
    asset = validate_return_series(asset_returns, label="asset return series")
    spy = validate_return_series(spy_returns, label="SPY return series")
    rf = validate_return_series(risk_free_daily, label="risk-free series")
    joined = pd.DataFrame({"asset": asset, "spy": spy, "rf": rf}).dropna()
    n = len(joined)
    if n < MIN_OBS_CAPM_REGRESSION:
        return InsufficientObservations("capm_regression", MIN_OBS_CAPM_REGRESSION, n)

    excess = pd.DataFrame(
        {
            "asset_excess": joined["asset"] - joined["rf"],
            "spy_excess": joined["spy"] - joined["rf"],
        },
        index=joined.index,
    )
    return _fit(
        excess, y_col="asset_excess", regressor_names=["spy_excess"], model="capm_regression"
    )


def ff3_regression(
    asset_returns: pd.Series,
    mkt_rf: pd.Series,
    smb: pd.Series,
    hml: pd.Series,
    risk_free_daily: pd.Series,
) -> FactorRegressionResult | InsufficientObservations | UndefinedResult:
    """OLS of ``asset``'s daily excess return on Ken French Mkt-RF/SMB/HML,
    with Newey-West (HAC) inference, over the one common inner-joined sample.

    ``(r_i - r_f) = alpha + beta_mkt*MktRF + beta_smb*SMB + beta_hml*HML + eps``.
    All five series (asset, RF, Mkt-RF, SMB, HML) are validated independently
    and then joined exactly once - no coefficient or diagnostic ever uses a
    different date sample than any other.
    """
    asset = validate_return_series(asset_returns, label="asset return series")
    mkt = validate_return_series(mkt_rf, label="Mkt-RF series")
    smb_series = validate_return_series(smb, label="SMB series")
    hml_series = validate_return_series(hml, label="HML series")
    rf = validate_return_series(risk_free_daily, label="risk-free series")
    joined = pd.DataFrame(
        {"asset": asset, "mkt_rf": mkt, "smb": smb_series, "hml": hml_series, "rf": rf}
    ).dropna()
    n = len(joined)
    if n < MIN_OBS_FF3_REGRESSION:
        return InsufficientObservations("ff3_regression", MIN_OBS_FF3_REGRESSION, n)

    excess = pd.DataFrame(
        {
            "asset_excess": joined["asset"] - joined["rf"],
            "mkt_rf": joined["mkt_rf"],
            "smb": joined["smb"],
            "hml": joined["hml"],
        },
        index=joined.index,
    )
    return _fit(
        excess,
        y_col="asset_excess",
        regressor_names=["mkt_rf", "smb", "hml"],
        model="ff3_regression",
    )


__all__ = [
    "FactorRegressionResult",
    "RegressionCoefficient",
    "capm_regression",
    "ff3_regression",
    "newey_west_lags",
]
