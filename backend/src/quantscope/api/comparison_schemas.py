"""Wire schemas for ``GET /compare`` (Phase 3A).

``status`` values:

* ``ok`` - every requested ticker had enough persisted history and the aligned
  panel cleared the observation gate; ``normalized_performance`` /
  ``correlation`` are populated.
* ``insufficient_observations`` - every ticker has *some* persisted history for
  the source, but the common aligned panel is shorter than
  :data:`~quantscope.quant.conventions.MIN_OBS_COMPARISON` (this also covers
  "no common dates at all", which is simply the zero-observation case of the
  same gate).
* ``unavailable`` - at least one requested ticker has fewer than two persisted
  bars for the resolved source (``reason: "missing_price_history"``,
  ``unavailable_tickers`` names them). No comparison is attempted.

There is no ``assumptions`` sub-object here (unlike
``GET /securities/{ticker}/analytics``): almost none of that block's fields
(risk-free rate, Sharpe/VaR conventions) apply to a comparison response, so the
small set of provenance fields that do apply are kept flat.
"""

from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel

ComparisonStatus = Literal["ok", "insufficient_observations", "unavailable"]


class NormalizedPerformance(BaseModel):
    """Base-100 wealth index for every requested ticker, derived from the one
    common aligned-return panel. Every return in the panel is compounded in
    sequence - none is divided away to force a display convention (see
    :mod:`quantscope.quant.comparison`).

    ``dates`` and each ticker's series in ``series`` are the same length,
    ``observations_used + 1``. Index ``0`` is the base-``100`` anchor, before
    any return has been applied; its date is ``null`` because the calendar day
    "before" the first aligned return is not generally common to every
    requested security (each asset's own prior price may sit on a different
    date, or not exist at all), so assigning one would require a second,
    independent alignment outside the one authoritative panel - deliberately
    not attempted. Indices ``1..N`` are the ``observations_used`` aligned
    return dates, in order.
    """

    base_value: float = 100.0
    dates: list[datetime.date | None]
    series: dict[str, list[float]]


class CorrelationMatrix(BaseModel):
    """Pearson correlation of the aligned return panel.

    ``tickers`` gives the row/column order (matching the parent response's
    top-level ``tickers``); ``matrix`` is square and symmetric. A cell is
    ``null`` - never ``0.0`` and never a raw ``NaN`` - whenever either ticker
    has zero return variance over the panel, including a zero-variance
    ticker's own diagonal (correlation of a constant series with itself is the
    indeterminate form ``0 / 0``, not ``1``). See ``zero_variance_tickers`` on
    the parent response for which tickers triggered this.
    """

    tickers: list[str]
    matrix: list[list[float | None]]


class ComparisonResponse(BaseModel):
    status: ComparisonStatus
    tickers: list[str]
    source: str
    adjustment_basis: Literal["adjusted_close"] = "adjusted_close"
    requested_start: datetime.date | None
    requested_end: datetime.date | None
    aligned_start: datetime.date | None
    aligned_end: datetime.date | None
    observations_used: int | None
    required: int | None
    reason: str | None
    unavailable_tickers: list[str] | None
    zero_variance_tickers: list[str] | None
    normalized_performance: NormalizedPerformance | None
    correlation: CorrelationMatrix | None


__all__ = [
    "ComparisonResponse",
    "ComparisonStatus",
    "CorrelationMatrix",
    "NormalizedPerformance",
]
