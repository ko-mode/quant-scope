"""Daily simple returns, the cumulative wealth index and descriptive stats.

Total return is taken from the adjusted-close price series (ADR 0012): V1 treats
the vendor adjusted close as the total-return price. Returns are simple
(arithmetic), ``r_t = P_t / P_{t-1} - 1``; the first price yields no return
observation (ADR 0017).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantscope.quant.conventions import MIN_OBS_RETURN_STATS, STDDEV_DDOF
from quantscope.quant.frames import validate_price_series, validate_return_series
from quantscope.quant.results import InsufficientObservations, QuantInputError


@dataclass(frozen=True, slots=True)
class ReturnSummary:
    """Descriptive statistics of a daily return series (no annualisation)."""

    observations_used: int
    mean_daily_return: float
    stdev_daily_return: float
    cumulative_return: float
    min_daily_return: float
    max_daily_return: float


def simple_returns(prices: pd.Series) -> pd.Series:
    """Daily simple total returns from an adjusted-close price series.

    ``r_t = P_t / P_{t-1} - 1``. The result is indexed by ``prices.index[1:]``
    (the first price has no prior close). Raises :class:`QuantInputError` for a
    structurally invalid series or fewer than two prices.
    """
    validated = validate_price_series(prices)
    if len(validated) < 2:
        raise QuantInputError("at least two prices are required to compute a return")
    changes = validated / validated.shift(1) - 1.0
    return changes.iloc[1:].rename("return")


def cumulative_wealth_index(returns: pd.Series) -> pd.Series:
    """``W_t = prod_{i<=t} (1 + r_i)`` - growth of one unit, compounded daily."""
    validated = validate_return_series(returns)
    return (1.0 + validated).cumprod().rename("wealth_index")


def return_summary(returns: pd.Series) -> ReturnSummary | InsufficientObservations:
    """Mean / stdev / cumulative / min / max of a daily return series (gate: 60)."""
    validated = validate_return_series(returns)
    n = len(validated)
    if n < MIN_OBS_RETURN_STATS:
        return InsufficientObservations("return_summary", MIN_OBS_RETURN_STATS, n)
    compounded = float(np.prod(1.0 + validated.to_numpy(dtype="float64")))
    return ReturnSummary(
        observations_used=n,
        mean_daily_return=float(validated.mean()),
        stdev_daily_return=float(validated.std(ddof=STDDEV_DDOF)),
        cumulative_return=compounded - 1.0,
        min_daily_return=float(validated.min()),
        max_daily_return=float(validated.max()),
    )


__all__ = [
    "ReturnSummary",
    "cumulative_wealth_index",
    "return_summary",
    "simple_returns",
]
