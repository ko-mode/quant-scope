"""Frozen numerical conventions for the pure analytics engine (ADR 0017).

Every user-facing statistic in :mod:`quantscope.quant` reads its constants from
here, so there is exactly one definition of the annualisation basis, the sample
standard-deviation convention and the minimum-observation gates. Service-layer
responses echo the relevant values in their ``assumptions`` block (ADR 0005).
"""

from __future__ import annotations

from typing import Final

# --- Annualisation ---------------------------------------------------------
TRADING_DAYS_PER_YEAR: Final = 252
"""Trading-session count for every annualisation (sessions, never calendar days).

Volatility is annualised by ``sqrt(TRADING_DAYS_PER_YEAR)`` and the Sharpe ratio
by the same factor. This assumes serially independent daily returns; the
annualised figure is *reported, not corrected*, for autocorrelation (ADR 0017).
"""

# --- Sample statistics ---------------------------------------------------
STDDEV_DDOF: Final = 1
"""Delta-degrees-of-freedom for every standard deviation (sample, not population)."""

# --- Historical VaR / Expected Shortfall --------------------------------
VAR_CONFIDENCE_LEVELS: Final[tuple[float, float]] = (0.95, 0.99)
"""Confidence levels reported for 1-day historical VaR / ES."""

VAR_ES_HORIZON_DAYS: Final = 1
"""V1 horizon: one trading day. No square-root-of-time or multi-day scaling."""

# --- Minimum usable daily-return observations (ADR 0017) ---------------
MIN_OBS_RETURN_STATS: Final = 60
MIN_OBS_VOLATILITY: Final = 60
MIN_OBS_DRAWDOWN: Final = 60
MIN_OBS_SHARPE: Final = 126
MIN_OBS_BETA: Final = 126
MIN_OBS_HISTORICAL_VAR: Final = 126
MIN_OBS_HISTORICAL_ES: Final = 126
MIN_OBS_FF3_REGRESSION: Final = 250
"""Reserved for the Phase 3 Fama-French regression; not consumed in Phase 2A."""

MIN_OBSERVATIONS: Final[dict[str, int]] = {
    "return_summary": MIN_OBS_RETURN_STATS,
    "annualised_volatility": MIN_OBS_VOLATILITY,
    "drawdown": MIN_OBS_DRAWDOWN,
    "sharpe_ratio": MIN_OBS_SHARPE,
    "capm_beta": MIN_OBS_BETA,
    "historical_var_es": max(MIN_OBS_HISTORICAL_VAR, MIN_OBS_HISTORICAL_ES),
    "ff3_regression": MIN_OBS_FF3_REGRESSION,
}
"""Metric name -> its minimum-observation gate, for a single lookup point."""

__all__ = [
    "MIN_OBSERVATIONS",
    "MIN_OBS_BETA",
    "MIN_OBS_DRAWDOWN",
    "MIN_OBS_FF3_REGRESSION",
    "MIN_OBS_HISTORICAL_ES",
    "MIN_OBS_HISTORICAL_VAR",
    "MIN_OBS_RETURN_STATS",
    "MIN_OBS_SHARPE",
    "MIN_OBS_VOLATILITY",
    "STDDEV_DDOF",
    "TRADING_DAYS_PER_YEAR",
    "VAR_CONFIDENCE_LEVELS",
    "VAR_ES_HORIZON_DAYS",
]
