"""Volatility, 1-day historical VaR / Expected Shortfall and CAPM beta (ADR 0017).

All three consume a daily simple-return series (see :mod:`quantscope.quant.returns`).
Conventions, verbatim from ADR 0017:

* **Volatility** - ``std(r, ddof=1)`` annualised by ``sqrt(252)``.
* **Historical VaR** - ``VaR_alpha = -(empirical (1 - alpha) quantile of daily
  returns)``, reported as a positive loss. The quantile is the *lower* empirical
  order statistic (no interpolation), so it is an actually observed return and
  deterministic under ties.
* **Historical ES** - ``ES_alpha = -(mean of daily returns at or below that
  quantile)``. One trading day only; no square-root-of-time scaling.
* **CAPM beta** - OLS slope of the asset's daily excess return on the
  benchmark's daily excess return, intercept included, on the inner-joined
  trading dates. Fitted with :func:`numpy.linalg.lstsq`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantscope.quant.conventions import (
    MIN_OBS_BETA,
    MIN_OBS_HISTORICAL_ES,
    MIN_OBS_HISTORICAL_VAR,
    MIN_OBS_VOLATILITY,
    STDDEV_DDOF,
    TRADING_DAYS_PER_YEAR,
    VAR_ES_HORIZON_DAYS,
)
from quantscope.quant.frames import validate_return_series
from quantscope.quant.results import InsufficientObservations, QuantInputError, UndefinedResult

_VAR_ES_REQUIRED = max(MIN_OBS_HISTORICAL_VAR, MIN_OBS_HISTORICAL_ES)


@dataclass(frozen=True, slots=True)
class VolatilityResult:
    daily_volatility: float
    annualised_volatility: float
    observations_used: int
    trading_days_per_year: int


@dataclass(frozen=True, slots=True)
class HistoricalVarEsResult:
    confidence: float
    var: float
    expected_shortfall: float
    threshold_return: float
    tail_observations: int
    observations_used: int
    horizon_days: int = VAR_ES_HORIZON_DAYS
    method: str = "historical_lower_quantile"


@dataclass(frozen=True, slots=True)
class BetaResult:
    beta: float
    alpha_daily: float
    r_squared: float | None
    observations_used: int
    aligned_start: pd.Timestamp
    aligned_end: pd.Timestamp


def annualised_volatility(returns: pd.Series) -> VolatilityResult | InsufficientObservations:
    """Sample daily volatility (``ddof=1``) and its ``sqrt(252)`` annualisation.

    A constant return series yields ``0.0`` for both figures - a legitimate
    value, not a suppressed one.
    """
    validated = validate_return_series(returns)
    n = len(validated)
    if n < MIN_OBS_VOLATILITY:
        return InsufficientObservations("annualised_volatility", MIN_OBS_VOLATILITY, n)
    daily = float(validated.std(ddof=STDDEV_DDOF))
    return VolatilityResult(
        daily_volatility=daily,
        annualised_volatility=daily * math.sqrt(TRADING_DAYS_PER_YEAR),
        observations_used=n,
        trading_days_per_year=TRADING_DAYS_PER_YEAR,
    )


def historical_var_es(
    returns: pd.Series, confidence: float
) -> HistoricalVarEsResult | InsufficientObservations:
    """1-day historical VaR and ES at ``confidence`` (e.g. ``0.95``, ``0.99``).

    ``confidence`` must lie in ``(0, 1)``. The tail is ``{r_t : r_t <= r*}`` where
    ``r*`` is the lower empirical ``(1 - confidence)`` quantile; ``var`` and
    ``expected_shortfall`` are positive loss magnitudes (``-r*`` and
    ``-mean(tail)``).
    """
    if not 0.0 < confidence < 1.0:
        raise QuantInputError(f"confidence must lie in (0, 1), got {confidence!r}")
    validated = validate_return_series(returns)
    n = len(validated)
    if n < _VAR_ES_REQUIRED:
        return InsufficientObservations("historical_var_es", _VAR_ES_REQUIRED, n)
    values = np.sort(validated.to_numpy(dtype="float64"))
    threshold = float(np.quantile(values, 1.0 - confidence, method="lower"))
    tail = values[values <= threshold]
    return HistoricalVarEsResult(
        confidence=confidence,
        var=-threshold,
        expected_shortfall=-float(tail.mean()),
        threshold_return=threshold,
        tail_observations=int(tail.size),
        observations_used=n,
    )


def capm_beta(
    asset_returns: pd.Series,
    benchmark_returns: pd.Series,
    risk_free_daily: pd.Series | None = None,
) -> BetaResult | InsufficientObservations | UndefinedResult:
    """OLS beta of ``asset`` vs ``benchmark`` excess returns on shared dates.

    Regression: ``(r_i - r_f) = alpha + beta * (r_m - r_f) + eps``, intercept
    included, over the inner join of the input dates (and of ``risk_free_daily``
    when supplied; otherwise ``r_f = 0``). ``alpha_daily`` is a daily figure and
    is never annualised here.

    Returns :class:`UndefinedResult` when the benchmark's excess return has zero
    variance (``beta`` itself is then undefined). When only the *asset's* excess
    return is constant, ``beta`` and ``alpha_daily`` are still well defined and
    returned, but ``r_squared`` is ``None`` - ``R^2 = 1 - SS_res / SS_tot`` is a
    ``0 / 0`` indeterminate form there, not zero.
    """
    asset = validate_return_series(asset_returns, label="asset return series")
    benchmark = validate_return_series(benchmark_returns, label="benchmark return series")
    frame = pd.DataFrame({"asset": asset, "benchmark": benchmark})
    if risk_free_daily is not None:
        rf = validate_return_series(risk_free_daily, label="risk-free series")
        frame = frame.join(rf.rename("rf"), how="inner")
    else:
        frame["rf"] = 0.0
    frame = frame.dropna()
    n = len(frame)
    if n < MIN_OBS_BETA:
        return InsufficientObservations("capm_beta", MIN_OBS_BETA, n)

    excess_asset = (frame["asset"] - frame["rf"]).to_numpy(dtype="float64")
    excess_bench = (frame["benchmark"] - frame["rf"]).to_numpy(dtype="float64")
    if excess_bench.min() == excess_bench.max():
        return UndefinedResult("capm_beta", "benchmark excess return has zero variance", n)

    design = np.column_stack([np.ones(n), excess_bench])
    coeffs, _residuals, _rank, _singular_values = np.linalg.lstsq(design, excess_asset, rcond=None)
    alpha, beta = float(coeffs[0]), float(coeffs[1])
    fitted = design @ coeffs
    r_squared: float | None
    if excess_asset.min() == excess_asset.max():
        # Constant dependent variable: SS_tot == 0, so R^2 = 1 - SS_res/SS_tot
        # is 0 / 0 (undefined), not 0. beta / alpha stay valid.
        r_squared = None
    else:
        ss_res = float(np.sum((excess_asset - fitted) ** 2))
        ss_tot = float(np.sum((excess_asset - excess_asset.mean()) ** 2))
        r_squared = 1.0 - ss_res / ss_tot

    index = frame.index
    return BetaResult(
        beta=beta,
        alpha_daily=alpha,
        r_squared=r_squared,
        observations_used=n,
        aligned_start=pd.Timestamp(index[0]),
        aligned_end=pd.Timestamp(index[-1]),
    )


__all__ = [
    "BetaResult",
    "HistoricalVarEsResult",
    "VolatilityResult",
    "annualised_volatility",
    "capm_beta",
    "historical_var_es",
]
