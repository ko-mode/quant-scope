"""XNYS session-continuity checks (QS-01 / ADR 0006; bounds: RA-01)."""

from __future__ import annotations

import exchange_calendars as xcals
import pandas as pd
import pytest

from quantscope.data.calendar import (
    CALENDAR_END,
    CALENDAR_START,
    session_continuous_returns,
    valid_return_adjacency_mask,
    valid_session_mask,
)


def test_valid_session_mask_rejects_weekend_and_holiday() -> None:
    dates = pd.Series(
        pd.to_datetime(
            [
                "2024-01-02",  # Tuesday - real session
                "2024-01-06",  # Saturday - not a session
                "2024-01-01",  # New Year's Day - holiday, not a session
                "2024-01-03",  # Wednesday - real session
            ]
        )
    )
    mask = valid_session_mask(dates)
    assert list(mask) == [True, False, False, True]


def test_valid_session_mask_empty_series() -> None:
    empty = pd.Series([], dtype="datetime64[ns]")
    mask = valid_session_mask(empty)
    assert len(mask) == 0


def test_valid_return_adjacency_mask_continuous_sessions_all_valid() -> None:
    # 2024-01-02 .. 2024-01-05: four consecutive real XNYS sessions, no gap.
    dates = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    mask = valid_return_adjacency_mask(dates)
    assert list(mask) == [True, True, True]
    assert list(mask.index) == list(dates[1:])


def test_valid_return_adjacency_mask_flags_a_missing_interior_session() -> None:
    # 2024-01-02 (Tue), 2024-01-03 (Wed) present; 2024-01-04 (Thu) missing
    # entirely from persisted history; 2024-01-05 (Fri) present. The
    # 01-03 -> 01-05 adjacency spans a missing session and must be flagged.
    dates = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-05"])
    mask = valid_return_adjacency_mask(dates)
    assert list(mask) == [True, False]


def test_valid_return_adjacency_mask_flags_a_weekend_adjacency() -> None:
    # Friday -> Saturday: Saturday is not a session at all, so this
    # adjacency (and the weekend date itself) is invalid.
    dates = pd.DatetimeIndex(["2024-01-05", "2024-01-06"])
    mask = valid_return_adjacency_mask(dates)
    assert list(mask) == [False]


def test_valid_return_adjacency_mask_holiday_gap() -> None:
    # 2024-01-15 is MLK Day (holiday); the session before is 01-12 (Fri), the
    # session after is 01-16 (Tue) - genuinely consecutive on the calendar,
    # since the holiday is not itself an expected session.
    dates = pd.DatetimeIndex(["2024-01-12", "2024-01-16"])
    mask = valid_return_adjacency_mask(dates)
    assert list(mask) == [True]


def test_valid_return_adjacency_mask_short_index() -> None:
    assert len(valid_return_adjacency_mask(pd.DatetimeIndex(["2024-01-02"]))) == 0
    assert len(valid_return_adjacency_mask(pd.DatetimeIndex([]))) == 0


def test_session_continuous_returns_excludes_only_the_gapped_adjacency() -> None:
    # 01-02, 01-03 present; 01-04 (Thursday) missing entirely; 01-05 present.
    # The price bars are untouched - 100/101/103 all remain valid prices -
    # only the 01-03 -> 01-05 return (which would span the missing session)
    # is excluded; the 01-02 -> 01-03 return is unaffected.
    dates = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-05"])
    prices = pd.Series([100.0, 101.0, 103.0], index=dates)
    returns = session_continuous_returns(prices)
    assert list(returns.index) == [dates[1]]
    assert returns.iloc[0] == pytest.approx(101.0 / 100.0 - 1.0)


def test_session_continuous_returns_fully_continuous_history_is_unaffected() -> None:
    dates = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    prices = pd.Series([100.0, 101.0, 99.0, 102.0], index=dates)
    returns = session_continuous_returns(prices)
    assert len(returns) == 3
    assert list(returns.index) == list(dates[1:])


def test_session_continuous_returns_holiday_gap_is_not_treated_as_missing() -> None:
    # 2024-01-15 is MLK Day - not an expected session, so 01-12 -> 01-16 is a
    # genuinely continuous adjacency and must not be excluded.
    dates = pd.DatetimeIndex(["2024-01-12", "2024-01-16"])
    prices = pd.Series([100.0, 105.0], index=dates)
    returns = session_continuous_returns(prices)
    assert list(returns.index) == [dates[1]]
    assert returns.iloc[0] == pytest.approx(0.05)


# --- RA-01: stable, current-date-independent calendar bounds -------------
#
# `exchange_calendars.get_calendar` defaults to a *rolling* window (20 years
# before / 1 year after `pandas.Timestamp.now()`), so a fixed historical date
# could raise `DateOutOfBounds` on one run and not another purely because the
# clock moved. These tests exercise dates and bounds nowhere near "today" -
# 1929 and 1995 - and would fail with a `DateOutOfBounds` under the library's
# rolling default were `quantscope.data.calendar` still using it.


def test_calendar_bounds_are_fixed_constants_not_derived_from_today() -> None:
    assert pd.Timestamp("1900-01-01") == CALENDAR_START
    assert pd.Timestamp("2099-12-31") == CALENDAR_END


def test_valid_session_mask_handles_dates_decades_before_2006() -> None:
    # 1929-10-24 ("Black Thursday") and 1929-10-29 ("Black Tuesday") were
    # both real NYSE trading sessions; 1929-10-27 was a Sunday.
    dates = pd.Series(pd.to_datetime(["1929-10-24", "1929-10-27", "1929-10-29"]))
    mask = valid_session_mask(dates)
    assert list(mask) == [True, False, True]


def test_valid_return_adjacency_mask_flags_a_missing_session_before_2006() -> None:
    # 1995-06-13 (Tue), 1995-06-14 (Wed) present; 1995-06-15 (Thu) missing
    # entirely from persisted history; 1995-06-16 (Fri) present. All four are
    # real XNYS sessions, decades before exchange_calendars' rolling default
    # window would even start.
    dates = pd.DatetimeIndex(["1995-06-13", "1995-06-14", "1995-06-16"])
    mask = valid_return_adjacency_mask(dates)
    assert list(mask) == [True, False]


def test_session_continuous_returns_before_2006_excludes_only_the_gapped_adjacency() -> None:
    dates = pd.DatetimeIndex(["1995-06-13", "1995-06-14", "1995-06-16"])
    prices = pd.Series([50.0, 51.0, 53.0], index=dates)
    returns = session_continuous_returns(prices)
    # The 06-14 price remains valid and usable - it still anchors nothing
    # downstream of the excluded return, but it is not dropped or flagged.
    assert list(returns.index) == [dates[1]]
    assert returns.iloc[0] == pytest.approx(51.0 / 50.0 - 1.0)


def test_valid_session_mask_accepts_dates_at_the_calendar_boundaries() -> None:
    # The first and last supported sessions must resolve without raising.
    dates = pd.Series([CALENDAR_START, CALENDAR_END])
    mask = valid_session_mask(dates)
    assert len(mask) == 2


def test_dates_outside_the_supported_range_raise_date_out_of_bounds_not_a_status() -> None:
    # A date genuinely outside [CALENDAR_START, CALENDAR_END] is a real
    # defect (a corrupted date, a parsing bug), never a thin-data condition -
    # it must raise, not be swallowed into insufficient_observations/undefined.
    before_range = pd.Series(pd.to_datetime(["1850-01-01"]))
    with pytest.raises(xcals.errors.DateOutOfBounds):
        valid_session_mask(before_range)

    after_range = pd.DatetimeIndex(["2024-01-02", "2200-01-02"])
    with pytest.raises(xcals.errors.DateOutOfBounds):
        valid_return_adjacency_mask(after_range)
