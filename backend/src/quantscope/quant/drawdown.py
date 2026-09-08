"""Drawdown analytics from the cumulative wealth index (ADR 0017).

``W_t = prod_{i<=t} (1 + r_i)``; ``DD_t = W_t / max_{s<=t} W_s - 1 <= 0``, where
the running maximum **includes the pre-return anchor wealth of 1.0** - a return
series that starts with a loss is itself a drawdown from that anchor, not from
its own first (already-diminished) wealth value. The maximum drawdown is
``min_t DD_t``. For a genuine drawdown episode the result carries the
running-peak date, the trough date and - if wealth later regains the peak
within the window - the recovery date. For a series that never draws down,
``max_drawdown`` is ``0.0`` and every date field is ``None`` (no episode
occurred).

**Peak-date semantics when the peak is the anchor itself.** The anchor
(wealth ``1.0``) has no date within ``returns.index`` - it is, by definition,
the wealth immediately *before* the first return. When the running peak
governing the maximum drawdown is that anchor (i.e. wealth never rises back to
``1.0`` before the trough), the caller may supply ``anchor_date`` - the actual
calendar date of the last price *before* the first return (the service layer
already has this: it is ``prices.index[0]``, one date earlier than
``returns.index[0]``) - and it is reported as ``peak_date`` verbatim, since it
is the truthful date of that peak. When no ``anchor_date`` is supplied,
``peak_date`` is ``None``, meaning "the peak precedes the first available
return observation" - not "no episode occurred" (`max_drawdown` distinguishes
the two: it is `0.0` only when there truly is no episode).
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


def drawdown_analysis(
    returns: pd.Series, *, anchor_date: pd.Timestamp | None = None
) -> DrawdownResult | InsufficientObservations:
    """Drawdown series, maximum drawdown and its peak / trough / recovery dates.

    ``anchor_date`` - the calendar date of the last price *before* the first
    return (``prices.index[0]``, one date earlier than ``returns.index[0]``) -
    is optional and used only as ``peak_date`` in the edge case where the
    running peak is the pre-return anchor wealth itself (see module docstring).
    """
    validated = validate_return_series(returns)
    n = len(validated)
    if n < MIN_OBS_DRAWDOWN:
        return InsufficientObservations("drawdown", MIN_OBS_DRAWDOWN, n)

    wealth = (1.0 + validated).cumprod()
    # The running maximum can never fall below the pre-return anchor of 1.0 -
    # equivalent to prepending a 1.0 anchor before taking cummax().
    running_max = wealth.cummax().clip(lower=1.0)
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
    # When the peak is the anchor itself (1.0, never reached by an observed
    # wealth value before the trough), there is no such date in this series.
    wealth_to_trough = wealth.iloc[: trough_pos + 1].to_numpy(dtype="float64")
    candidates = (wealth_to_trough >= peak_level).nonzero()[0]
    if candidates.size > 0:
        peak_pos = int(candidates[-1])
        peak_date: pd.Timestamp | None = pd.Timestamp(wealth.index[peak_pos])
    else:
        peak_date = pd.Timestamp(anchor_date) if anchor_date is not None else None

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
