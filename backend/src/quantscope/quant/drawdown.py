"""Drawdown analytics from the cumulative wealth index (ADR 0017).

``W_t = prod_{i<=t} (1 + r_i)``; ``DD_t = W_t / max_{s<=t} W_s - 1 <= 0``. The
maximum drawdown is ``min_t DD_t``. For a genuine drawdown episode the result
carries the running-peak date, the trough date and - if wealth later regains the
peak within the window - the recovery date. For a series that never draws down,
``max_drawdown`` is ``0.0`` and every date field is ``None`` (no episode occurred).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quantscope.quant.conventions import MIN_OBS_DRAWDOWN
from quantscope.quant.frames import validate_return_series
from quantscope.quant.results import InsufficientObservations


@dataclass(frozen=True, slots=True)
class DrawdownResult:
    drawdown_series: pd.Series
    max_drawdown: float
    peak_date: pd.Timestamp | None
    trough_date: pd.Timestamp | None
    recovery_date: pd.Timestamp | None
    recovered: bool
    observations_used: int


def drawdown_analysis(returns: pd.Series) -> DrawdownResult | InsufficientObservations:
    """Drawdown series, maximum drawdown and its peak / trough / recovery dates."""
    validated = validate_return_series(returns)
    n = len(validated)
    if n < MIN_OBS_DRAWDOWN:
        return InsufficientObservations("drawdown", MIN_OBS_DRAWDOWN, n)

    wealth = (1.0 + validated).cumprod()
    running_max = wealth.cummax()
    drawdown = (wealth / running_max - 1.0).rename("drawdown")
    max_drawdown = float(drawdown.min())

    if max_drawdown >= 0.0:
        return DrawdownResult(
            drawdown_series=drawdown,
            max_drawdown=0.0,
            peak_date=None,
            trough_date=None,
            recovery_date=None,
            recovered=False,
            observations_used=n,
        )

    trough_pos = int(drawdown.to_numpy(dtype="float64").argmin())
    trough_date = pd.Timestamp(drawdown.index[trough_pos])
    peak_level = float(running_max.iloc[trough_pos])

    # The peak is the most recent date at or before the trough whose wealth set
    # the running maximum (float-exact, since cummax carries that same value).
    wealth_to_trough = wealth.iloc[: trough_pos + 1].to_numpy(dtype="float64")
    peak_pos = int((wealth_to_trough >= peak_level).nonzero()[0][-1])
    peak_date = pd.Timestamp(wealth.index[peak_pos])

    # Recovery: the first date after the trough whose wealth regains the peak.
    after = wealth.iloc[trough_pos + 1 :]
    regained = (after.to_numpy(dtype="float64") >= peak_level).nonzero()[0]
    if regained.size > 0:
        recovery_date: pd.Timestamp | None = pd.Timestamp(after.index[int(regained[0])])
        recovered = True
    else:
        recovery_date = None
        recovered = False

    return DrawdownResult(
        drawdown_series=drawdown,
        max_drawdown=max_drawdown,
        peak_date=peak_date,
        trough_date=trough_date,
        recovery_date=recovery_date,
        recovered=recovered,
        observations_used=n,
    )


__all__ = ["DrawdownResult", "drawdown_analysis"]
