"""Annualised Sharpe ratio (ADR 0017).

``SR = mean(r_t - r_f,t) / std(r_t - r_f,t, ddof=1) * sqrt(252)``.

The risk-free input is a **daily** series (Ken French daily ``RF``, ADR 0013).
As a convenience a scalar *annual* rate may be supplied instead; it is converted
to an equivalent daily rate by compounding, ``r_f,daily = (1 + r_ann)^(1/252) -
1``, and subtracted from every daily return - never the annual rate itself. The
``sqrt(252)`` annualisation assumes serially independent daily excess returns
(ADR 0017); it is reported, not corrected.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantscope.quant.conventions import MIN_OBS_SHARPE, STDDEV_DDOF, TRADING_DAYS_PER_YEAR
from quantscope.quant.frames import validate_return_series
from quantscope.quant.results import InsufficientObservations, QuantInputError, UndefinedResult


@dataclass(frozen=True, slots=True)
class SharpeResult:
    sharpe_ratio: float
    mean_daily_excess_return: float
    daily_excess_volatility: float
    observations_used: int
    trading_days_per_year: int
    risk_free_basis: str


def _daily_from_annual(annual_risk_free: float) -> float:
    return float((1.0 + annual_risk_free) ** (1.0 / TRADING_DAYS_PER_YEAR) - 1.0)


def sharpe_ratio(
    returns: pd.Series,
    *,
    risk_free_daily: pd.Series | None = None,
    annual_risk_free: float | None = None,
) -> SharpeResult | InsufficientObservations | UndefinedResult:
    """Annualised Sharpe ratio of ``returns`` (gate: 126 excess observations).

    Supply at most one of ``risk_free_daily`` (aligned by inner join) or
    ``annual_risk_free`` (a scalar, compounded to a daily rate); with neither,
    the risk-free rate is ``0``. Returns :class:`UndefinedResult` when the excess
    return series has zero variance.
    """
    if risk_free_daily is not None and annual_risk_free is not None:
        raise QuantInputError("supply at most one of risk_free_daily / annual_risk_free")
    validated = validate_return_series(returns)

    if risk_free_daily is not None:
        rf = validate_return_series(risk_free_daily, label="risk-free series")
        aligned = pd.DataFrame({"r": validated, "rf": rf}).dropna()
        excess = (aligned["r"] - aligned["rf"]).to_numpy(dtype="float64")
        basis = "daily_series"
    elif annual_risk_free is not None:
        if annual_risk_free <= -1.0:
            raise QuantInputError("annual_risk_free must be greater than -1")
        excess = validated.to_numpy(dtype="float64") - _daily_from_annual(annual_risk_free)
        basis = "annual_scalar_compounded"
    else:
        excess = validated.to_numpy(dtype="float64")
        basis = "zero"

    n = int(excess.size)
    if n < MIN_OBS_SHARPE:
        return InsufficientObservations("sharpe_ratio", MIN_OBS_SHARPE, n)

    if excess.min() == excess.max():
        return UndefinedResult("sharpe_ratio", "zero excess-return variance", n)
    mean_excess = float(excess.mean())
    std_excess = float(np.std(excess, ddof=STDDEV_DDOF))
    if std_excess == 0.0:  # pragma: no cover - defensive: min != max but std underflows
        return UndefinedResult("sharpe_ratio", "zero excess-return variance", n)

    return SharpeResult(
        sharpe_ratio=mean_excess / std_excess * math.sqrt(TRADING_DAYS_PER_YEAR),
        mean_daily_excess_return=mean_excess,
        daily_excess_volatility=std_excess,
        observations_used=n,
        trading_days_per_year=TRADING_DAYS_PER_YEAR,
        risk_free_basis=basis,
    )


__all__ = ["SharpeResult", "sharpe_ratio"]
