"""Wire schemas for ``GET /securities/{ticker}/analytics`` (Phase 2B).

Each metric is a small, flat model with a ``status`` discriminator. Value fields
are populated only when ``status == "ok"``; otherwise they are ``null`` and the
suppression fields (``required`` / ``observations_used`` / ``reason``) carry the
explanation. This mirrors the Phase 2A result dataclasses
(:class:`~quantscope.quant.InsufficientObservations`,
:class:`~quantscope.quant.UndefinedResult`, and the per-metric results) one to
one - deliberately no generic envelope hierarchy.

``status`` values:

* ``ok`` - the metric was computed.
* ``insufficient_observations`` - the return series is shorter than the metric's
  gate (ADR 0017); ``required`` / ``observations_used`` are set.
* ``undefined`` - enough data, but the statistic is undefined (zero-variance
  denominator); ``reason`` is set.
* ``unavailable`` - a required *input series* is not persisted at all. In
  Phase 2B this is Sharpe and CAPM beta, which ADR 0017 defines against the
  Ken French daily ``RF`` series that ADR 0013 stores in ``factor_return`` - a
  table that does not exist until migration M2. No constant/zero RF is
  substituted (ADR 0013 rejected that).

Metric numbers are ``float`` end to end (the quant engine's precision), so they
serialise as JSON numbers and OpenAPI describes them as ``number``.
"""

from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel

MetricStatus = Literal["ok", "insufficient_observations", "undefined", "unavailable"]


class MetricBase(BaseModel):
    """Fields every metric object carries regardless of ``status``."""

    status: MetricStatus
    observations_used: int | None = None
    required: int | None = None
    reason: str | None = None


class ReturnSummaryMetric(MetricBase):
    mean_daily_return: float | None = None
    stdev_daily_return: float | None = None
    cumulative_return: float | None = None
    min_daily_return: float | None = None
    max_daily_return: float | None = None


class VolatilityMetric(MetricBase):
    daily_volatility: float | None = None
    annualised_volatility: float | None = None
    trading_days_per_year: int | None = None


class SharpeMetric(MetricBase):
    sharpe_ratio: float | None = None
    mean_daily_excess_return: float | None = None
    daily_excess_volatility: float | None = None
    trading_days_per_year: int | None = None
    risk_free_basis: str | None = None


class DrawdownMetric(MetricBase):
    max_drawdown: float | None = None
    peak_date: datetime.date | None = None
    trough_date: datetime.date | None = None
    recovery_date: datetime.date | None = None
    recovered: bool | None = None


class BetaMetric(MetricBase):
    beta: float | None = None
    alpha_daily: float | None = None
    r_squared: float | None = None
    aligned_start: datetime.date | None = None
    aligned_end: datetime.date | None = None


class VarEsMetric(MetricBase):
    confidence: float | None = None
    var: float | None = None
    expected_shortfall: float | None = None
    threshold_return: float | None = None
    tail_observations: int | None = None
    horizon_days: int | None = None
    method: str | None = None


class SuppressedMetric(BaseModel):
    """One entry in ``assumptions.suppressed`` - why a metric is not ``ok``."""

    metric: str
    status: MetricStatus
    required: int | None = None
    observations_used: int | None = None
    reason: str | None = None


class AnalyticsAssumptions(BaseModel):
    """ADR 0005 methodology block. Assembled by the service, not the engine."""

    as_of: datetime.date | None
    calendar: Literal["XNYS"] = "XNYS"
    annualisation_factor: int
    return_type: Literal["total"] = "total"
    adjustment_basis: Literal["adjusted_close"] = "adjusted_close"
    data_source: str
    missing_data_policy: str
    rf_source: str
    rf: float | None
    benchmark: str
    market_proxy: str
    var_horizon_days: int
    var_scaling: Literal["none"] = "none"
    confidence_levels: list[float]
    min_observations: dict[str, int]
    sharpe_annualisation_note: str
    suppressed: list[SuppressedMetric]


class AnalyticsResponse(BaseModel):
    ticker: str
    source: str
    adjustment_basis: Literal["adjusted_close"] = "adjusted_close"
    requested_start: datetime.date | None
    requested_end: datetime.date | None
    price_observations: int
    return_observations: int
    analytics_start: datetime.date | None
    analytics_end: datetime.date | None
    return_summary: ReturnSummaryMetric
    volatility: VolatilityMetric
    sharpe: SharpeMetric
    drawdown: DrawdownMetric
    beta: BetaMetric
    var_es_95: VarEsMetric
    var_es_99: VarEsMetric
    assumptions: AnalyticsAssumptions


__all__ = [
    "AnalyticsAssumptions",
    "AnalyticsResponse",
    "BetaMetric",
    "DrawdownMetric",
    "MetricBase",
    "MetricStatus",
    "ReturnSummaryMetric",
    "SharpeMetric",
    "SuppressedMetric",
    "VarEsMetric",
    "VolatilityMetric",
]
