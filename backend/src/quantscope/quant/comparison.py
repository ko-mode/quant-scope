"""Multi-security comparison: one common aligned-return panel, normalized
performance, and a Pearson correlation matrix (ADR 0017 "Multi-security
comparison").

Alignment algorithm (the one authoritative ordering)::

    adjusted-close prices per asset
      -> simple_returns() independently, per asset (each asset's own calendar,
         computed exactly as everywhere else in the engine - see returns.py)
      -> ONE N-way inner join of the resulting return series
      -> the aligned return panel: every output below is derived from this and
         only this panel - never a second, independent alignment

The inner join is deliberately done on already-computed **returns**, not on
raw prices followed by a price-level join. Joining prices first and taking
period-over-period changes afterward would risk a subtle, asset-specific bug:
dropping a date because *some other* asset lacks a price there can make two
dates that were never calendar-adjacent for a *given* asset become row-adjacent
in the joined frame, so a naive positional diff would silently compute a
multi-day return and label it as one trading day - for an asset that had no
gap in its own history at all. Computing each asset's returns first, from its
own unbroken calendar, and joining only the results avoids this entirely.

Normalized performance
-----------------------
Every return in the aligned panel is preserved and compounded - none is
divided away to force a display convention. Starting from a wealth of 100::

    wealth_0 (anchor)      = 100
    wealth_1 (1st aligned)  = 100 * (1 + r_1)
    wealth_2 (2nd aligned)  = wealth_1 * (1 + r_2)
    ...

So ``normalized_performance`` has **N + 1** rows for an N-row return panel:
the anchor plus one row per aligned return date. The anchor has **no market
date** - the calendar day "before" the panel's first aligned return is not
generally common to every requested security (each asset's own prior price
may sit on a different date, or not exist at all for a newly listed asset), so
assigning it a specific date would itself be a second, independent alignment
outside the one authoritative panel. The anchor's index label is
:data:`pandas.NaT`, explicitly representing "no date" rather than fabricating
one; the service layer maps this to a JSON ``null``.

Correlation
-----------
Pearson correlation of the aligned panel's columns. Because the panel has
already been through the N-way inner join, it contains **zero** NaNs by the
time :meth:`pandas.DataFrame.corr` runs - every pairwise cell is therefore
computed from the identical ``n`` rows. This is what makes ``.corr()`` safe to
call directly here: the "no pairwise-complete correlation" guarantee comes
from joining *before* correlating, not from any special behaviour of
``.corr()`` itself (on raw, ragged input it would default to pairwise-complete
exclusion of NaNs, which is exactly what ADR 0017 forbids).

A constant-return column makes pandas report ``NaN`` for every cell in that
column's row *and* column, including its own diagonal (correlation of a
constant series with itself is the indeterminate form ``0 / 0``, not `1`) -
this falls out of ``.corr()`` with no special-casing and is surfaced via
``zero_variance_tickers`` for transparency, not coerced to `0` or hidden.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from quantscope.quant.conventions import MIN_OBS_COMPARISON
from quantscope.quant.frames import validate_return_series
from quantscope.quant.results import InsufficientObservations, QuantInputError


@dataclass(frozen=True, slots=True)
class ComparisonPanel:
    """The one common panel every comparison statistic is derived from."""

    tickers: tuple[str, ...]
    observations_used: int
    aligned_start: pd.Timestamp
    aligned_end: pd.Timestamp
    normalized_performance: pd.DataFrame
    """Index: ``observations_used + 1`` rows - :data:`pandas.NaT` (the base-100
    anchor, no market date) followed by the ``observations_used`` aligned
    return dates. Columns: one per ticker, each starting at exactly ``100.0``
    at the anchor row."""
    returns: pd.DataFrame
    """The aligned ``observations_used``-row return panel itself. Internal to
    the engine/service layer - not wired to the public API in Phase 3A."""
    correlation: pd.DataFrame
    """``tickers`` x ``tickers`` Pearson correlation. ``NaN`` on any cell
    touching a zero-variance ticker (including that ticker's own diagonal)."""
    zero_variance_tickers: tuple[str, ...]


def compare_securities(
    returns: Mapping[str, pd.Series],
) -> ComparisonPanel | InsufficientObservations:
    """Build the one common aligned-return panel for 2+ securities and derive
    normalized performance (base 100, every return preserved) and a Pearson
    correlation matrix from it.

    Each value in ``returns`` must already be a valid daily simple-return
    series (see :func:`quantscope.quant.returns.simple_returns`) - this
    function does not fetch or derive returns itself, and does not accept
    fewer than two series. Returns :class:`InsufficientObservations` when the
    aligned panel has fewer than :data:`MIN_OBS_COMPARISON` common
    observations (this also covers "no common dates at all": an empty panel is
    simply the ``0``-observation case of the same gate).
    """
    if len(returns) < 2:
        raise QuantInputError("comparison requires at least two securities")

    tickers = tuple(returns.keys())
    validated = {
        ticker: validate_return_series(series, label=f"{ticker} return series")
        for ticker, series in returns.items()
    }
    # Dict-of-Series construction outer-aligns on the union of every series'
    # dates; dropna() then keeps only rows where EVERY column has a value -
    # the one true N-way inner join, not a pairwise one.
    panel = pd.DataFrame(validated).sort_index().dropna()
    n = len(panel)
    if n < MIN_OBS_COMPARISON:
        return InsufficientObservations("comparison", MIN_OBS_COMPARISON, n)

    growth = (1.0 + panel).cumprod()
    anchor = pd.DataFrame(
        [[1.0] * len(tickers)], columns=panel.columns, index=pd.DatetimeIndex([pd.NaT])
    )
    normalized_performance = 100.0 * pd.concat([anchor, growth])

    correlation = panel.corr(method="pearson")
    zero_variance_tickers = tuple(t for t in tickers if panel[t].min() == panel[t].max())

    return ComparisonPanel(
        tickers=tickers,
        observations_used=n,
        aligned_start=pd.Timestamp(panel.index[0]),
        aligned_end=pd.Timestamp(panel.index[-1]),
        normalized_performance=normalized_performance,
        returns=panel,
        correlation=correlation,
        zero_variance_tickers=zero_variance_tickers,
    )


__all__ = ["ComparisonPanel", "compare_securities"]
