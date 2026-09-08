"""Trading-session continuity for the XNYS calendar (ADR 0006).

Two independent checks, both needed to satisfy ADR 0006's "missing sessions
are explicit" decision without ever bridging a gap, interpolating a missing
price, or discarding an otherwise-valid history:

* :func:`valid_session_mask` - is each date a real XNYS session at all? Used
  at ingestion (:mod:`quantscope.data.validation`) to reject a persisted row
  whose date is not a real trading day (a weekend, a holiday, or any other
  non-session date from a malformed provider response) - the same class of
  defect as a non-positive price, and rejected the same way.
* :func:`valid_return_adjacency_mask` - for a sorted, unique index of
  already-valid session dates, is each adjacent pair
  (``price_dates[i-1]``, ``price_dates[i]``) consecutive on the XNYS
  calendar, with no expected session missing between them? Used by the
  services, immediately after :func:`quantscope.quant.returns.simple_returns`,
  to exclude the one return that would otherwise silently span a missing
  session and be miscounted as a single trading day's move. **The price bars
  themselves are never touched, dropped, or flagged by this check** - a valid
  price immediately after a gap remains valid data and anchors the *next*
  return normally. Only the specific return adjacency that crosses the gap is
  excluded from the series that reaches every downstream metric.

Deliberately outside :mod:`quantscope.quant` (ADR 0002): the pure engine is
calendar-agnostic by design (it also processes Ken French factor series,
which are not XNYS-anchored securities at all), so calendar knowledge lives
here, in the data layer, which already carries ``security.exchange``.

**Supported date range (RA-01, 2026-09-07).** ``exchange_calendars.get_calendar``
defaults to a *rolling* window - 20 years before, and 1 year after, whatever
``pandas.Timestamp.now()`` returns at import/call time - so the exact same
historical date could raise ``exchange_calendars.errors.DateOutOfBounds`` on
one day and not the next, purely because the calendar's implicit window
shifted. This module instead builds the calendar with fixed, explicit bounds
(:data:`CALENDAR_START`, :data:`CALENDAR_END`) that do not depend on the
current date, so behaviour is identical every day this code runs:

* ``CALENDAR_START = 1900-01-01`` - comfortably before every historical
  series QuantScope can ingest: Ken French factors from 1926-07-01 (ADR
  0009), Tiingo US-equity history to 1962 (ADR 0022).
* ``CALENDAR_END = 2099-12-31`` - a deliberately distant, round future bound
  so this module needs no maintenance for the foreseeable lifetime of the
  project, rather than tracking "today plus N years".

A date genuinely outside ``[CALENDAR_START, CALENDAR_END]`` - which no real
QuantScope security or factor date can be - still raises
``exchange_calendars.errors.DateOutOfBounds`` (a ``ValueError``) from
whichever function received it. Nothing in this module catches that error and
none of it is ever translated into ``insufficient_observations`` or any other
metric status: an out-of-supported-range date is a genuine defect (a
corrupted date, a parsing bug) worth a loud failure, not a thin-data
condition.
"""

from __future__ import annotations

from functools import lru_cache

import exchange_calendars as xcals
import pandas as pd

from quantscope.quant import simple_returns

XNYS = "XNYS"

#: Fixed, current-date-independent calendar bounds (RA-01). See the module
#: docstring's "Supported date range" section for the reasoning behind these
#: exact values.
CALENDAR_START = pd.Timestamp("1900-01-01")
CALENDAR_END = pd.Timestamp("2099-12-31")


@lru_cache(maxsize=4)
def _calendar(name: str) -> xcals.ExchangeCalendar:
    return xcals.get_calendar(name, start=CALENDAR_START, end=CALENDAR_END)


def valid_session_mask(dates: pd.Series, *, calendar: str = XNYS) -> pd.Series:
    """Boolean mask, same index as ``dates``: ``True`` where the date is a
    real session of ``calendar``, ``False`` for a weekend, a holiday, or any
    other non-trading date. ``dates`` holds ``datetime64``-like values.
    """
    if dates.empty:
        return pd.Series([], dtype=bool, index=dates.index)
    cal = _calendar(calendar)
    sessions = cal.sessions_in_range(pd.Timestamp(dates.min()), pd.Timestamp(dates.max()))
    return pd.Series(dates.isin(sessions).to_numpy(), index=dates.index, dtype=bool)


def valid_return_adjacency_mask(
    price_dates: pd.DatetimeIndex, *, calendar: str = XNYS
) -> pd.Series:
    """Boolean mask indexed by ``price_dates[1:]`` - the same index
    :func:`quantscope.quant.returns.simple_returns` produces from
    ``price_dates`` - so it can be applied directly to that function's output:
    ``returns[valid_return_adjacency_mask(prices.index)]``.

    ``True`` where ``price_dates[i-1]`` and ``price_dates[i]`` are consecutive
    ``calendar`` sessions (no expected session missing between them);
    ``False`` where at least one session is missing, meaning the return
    computed across that pair would silently span more than one trading day.

    Every ``price_dates`` entry is assumed to already be a valid session
    (ingestion rejects anything else via :func:`valid_session_mask`); a date
    that is not itself a session is defensively treated as invalidating both
    of its adjacencies rather than raising - this check must never be the
    reason a request fails outright.
    """
    if len(price_dates) < 2:
        return pd.Series([], dtype=bool, index=price_dates[1:])
    cal = _calendar(calendar)
    sessions = cal.sessions_in_range(pd.Timestamp(price_dates[0]), pd.Timestamp(price_dates[-1]))
    position = {ts: i for i, ts in enumerate(sessions)}
    positions = [position.get(pd.Timestamp(d)) for d in price_dates]

    def _is_continuous(prev: int | None, curr: int | None) -> bool:
        return prev is not None and curr is not None and curr - prev == 1

    valid = [_is_continuous(positions[i - 1], positions[i]) for i in range(1, len(price_dates))]
    return pd.Series(valid, index=price_dates[1:], dtype=bool)


def session_continuous_returns(prices: pd.Series, *, calendar: str = XNYS) -> pd.Series:
    """:func:`quantscope.quant.simple_returns` with the one return spanning
    each missing expected session excluded (QS-01, ADR 0006).

    The price bars themselves are never touched - a valid price immediately
    after a gap is not itself invalid, and still anchors the *next* return
    normally. Only the specific return adjacency that would otherwise
    silently span more than one XNYS session is excluded from the result.
    This is the one call every service makes in place of a bare
    ``simple_returns(prices)`` wherever ``prices`` is an actual XNYS
    security's adjusted-close series (never for Ken French factor series,
    which are already daily returns, not derived from a price series here).
    """
    returns = simple_returns(prices)
    price_dates = pd.DatetimeIndex(prices.index)
    return returns[valid_return_adjacency_mask(price_dates, calendar=calendar)]


__all__ = [
    "CALENDAR_END",
    "CALENDAR_START",
    "XNYS",
    "session_continuous_returns",
    "valid_return_adjacency_mask",
    "valid_session_mask",
]
