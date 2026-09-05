"""Wire schemas for ``GET /securities/{ticker}/factors`` (Phase 3B).

Returns the SPY-based CAPM regression and the Fama-French 3-factor regression
together, one response per ticker (ADR 0017 addendum, Phase 3B) - not one
model per request, unlike `docs/architecture.md`'s earlier `?model=ff3` sketch.

``FactorModelStatus`` preserves the same three-way distinction the rest of
the platform already uses (``insufficient_observations`` / ``undefined`` /
``unavailable``), applied independently to each of ``capm`` and ``ff3``:

* ``ok`` - the model is estimable; ``coefficients`` / ``r_squared`` /
  ``hac_lags`` are populated. Coefficient-level inference fields
  (``std_error`` / ``t_stat`` / ``p_value`` / ``ci_low`` / ``ci_high``) may
  still independently be ``null`` when the OLS ``estimate`` exists but that
  one statistic is mathematically undefined for it.
* ``insufficient_observations`` - every required input is present, but the
  one common aligned sample is shorter than the model's gate; ``required`` /
  ``observations_used`` are set.
* ``undefined`` - the aligned sample clears the gate, but the regression
  itself is not estimable (a zero-variance regressor, or a rank-deficient
  design); ``reason`` is set. Never collapsed into ``unavailable``.
* ``unavailable`` - a required *input series* is missing before alignment is
  even attempted (asset price history, the risk-free series, or - for FF3
  only - one of Mkt-RF/SMB/HML not ingested for the source); ``reason`` is
  set.

Alpha is reported only as the daily regression intercept - there is no
annualised-alpha field anywhere in this schema.
"""

from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel

FactorModelStatus = Literal["ok", "insufficient_observations", "undefined", "unavailable"]


class RegressionCoefficientSchema(BaseModel):
    """One OLS coefficient with Newey-West (HAC) inference.

    ``estimate`` is always populated for an ``ok`` model. The four inference
    fields are independently ``null`` - never ``0``, never a raw ``NaN`` or
    ``Infinity`` - when that statistic is undefined for this coefficient.
    """

    name: str
    estimate: float
    std_error: float | None = None
    t_stat: float | None = None
    p_value: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None


class FactorModelResult(BaseModel):
    status: FactorModelStatus
    required: int | None = None
    observations_used: int | None = None
    reason: str | None = None
    aligned_start: datetime.date | None = None
    aligned_end: datetime.date | None = None
    coefficients: list[RegressionCoefficientSchema] | None = None
    r_squared: float | None = None
    adjusted_r_squared: float | None = None
    hac_lags: int | None = None


class FactorsAssumptions(BaseModel):
    """Methodology / provenance block (ADR 0005). Assembled by the service."""

    capm_vs_ff3_note: str
    alpha_note: str
    adjustment_basis: Literal["adjusted_close"] = "adjusted_close"
    factor_source: str
    factor_frequency: Literal["daily"] = "daily"
    rf_source: str
    hac_lag_rule: str
    min_observations: dict[str, int]


class FactorsResponse(BaseModel):
    ticker: str
    source: str
    adjustment_basis: Literal["adjusted_close"] = "adjusted_close"
    requested_start: datetime.date | None
    requested_end: datetime.date | None
    capm: FactorModelResult
    ff3: FactorModelResult
    assumptions: FactorsAssumptions


__all__ = [
    "FactorModelResult",
    "FactorModelStatus",
    "FactorsAssumptions",
    "FactorsResponse",
    "RegressionCoefficientSchema",
]
