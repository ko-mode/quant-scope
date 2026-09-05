"""Pure quantitative analytics.

Every function in this package must be:

* **Deterministic** - same inputs produce the same outputs, always.
* **I/O-free** - no network, no filesystem, no database, no clock.
* **Framework-free** - no FastAPI, SQLAlchemy, Alembic, or pydantic imports.
  Inputs and outputs are numpy/pandas objects (validated at the boundary with
  pandera - see :mod:`quantscope.quant.frames`) or plain dataclasses.

The boundary is enforced by the ``import-linter`` contract in ``pyproject.toml``
and checked in CI. Callers in the service layer are responsible for loading
data, converting to/from wire schemas, and attaching the ``assumptions``
metadata block to responses.

Phase 2A implements the single-name analytics: daily simple returns, the
cumulative wealth index, descriptive return stats, annualised volatility, the
annualised Sharpe ratio, drawdown analytics, CAPM beta and 1-day historical
VaR / Expected Shortfall. Phase 3A adds multi-security comparison: one common
inner-joined return panel, normalized performance and Pearson correlation
(:mod:`quantscope.quant.comparison`). Phase 3B adds the SPY-based CAPM
regression and the Fama-French 3-factor regression, both with Newey-West
(HAC) inference (:mod:`quantscope.quant.factors`) - ``capm_beta`` is
unchanged and remains the sole basis for the Risk & Return "Beta vs SPY"
metric. Numerical conventions and the minimum-observation gates live in
:mod:`quantscope.quant.conventions` (ADR 0017).
"""

from __future__ import annotations

from quantscope.quant.comparison import ComparisonPanel, compare_securities
from quantscope.quant.conventions import (
    MIN_OBS_COMPARISON,
    MIN_OBSERVATIONS,
    STDDEV_DDOF,
    TRADING_DAYS_PER_YEAR,
    VAR_CONFIDENCE_LEVELS,
    VAR_ES_HORIZON_DAYS,
)
from quantscope.quant.drawdown import DrawdownResult, drawdown_analysis
from quantscope.quant.factors import (
    FactorRegressionResult,
    RegressionCoefficient,
    capm_regression,
    ff3_regression,
    newey_west_lags,
)
from quantscope.quant.performance import SharpeResult, sharpe_ratio
from quantscope.quant.results import (
    InsufficientObservations,
    QuantInputError,
    UndefinedResult,
)
from quantscope.quant.returns import (
    ReturnSummary,
    cumulative_wealth_index,
    return_summary,
    simple_returns,
)
from quantscope.quant.risk import (
    BetaResult,
    HistoricalVarEsResult,
    VolatilityResult,
    annualised_volatility,
    capm_beta,
    historical_var_es,
)

__all__ = [
    "MIN_OBSERVATIONS",
    "MIN_OBS_COMPARISON",
    "STDDEV_DDOF",
    "TRADING_DAYS_PER_YEAR",
    "VAR_CONFIDENCE_LEVELS",
    "VAR_ES_HORIZON_DAYS",
    "BetaResult",
    "ComparisonPanel",
    "DrawdownResult",
    "FactorRegressionResult",
    "HistoricalVarEsResult",
    "InsufficientObservations",
    "QuantInputError",
    "RegressionCoefficient",
    "ReturnSummary",
    "SharpeResult",
    "UndefinedResult",
    "VolatilityResult",
    "annualised_volatility",
    "capm_beta",
    "capm_regression",
    "compare_securities",
    "cumulative_wealth_index",
    "drawdown_analysis",
    "ff3_regression",
    "historical_var_es",
    "newey_west_lags",
    "return_summary",
    "sharpe_ratio",
    "simple_returns",
]
