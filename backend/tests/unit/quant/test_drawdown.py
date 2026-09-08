"""Drawdown analytics: known peak / trough / recovery on a built wealth path."""

from __future__ import annotations

import pandas as pd
import pytest

from quantscope.quant.drawdown import DrawdownResult, drawdown_analysis
from quantscope.quant.results import InsufficientObservations


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2023-01-02", periods=n)


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=_dates(len(values)), dtype="float64")


def test_known_episode_with_recovery() -> None:
    # 56 flat days, then +20% (peak), -25% (trough), +5%, +35% (new high).
    returns = [0.0] * 56 + [0.2, -0.25, 0.05, 0.35]
    dates = _dates(60)
    out = drawdown_analysis(_series(returns))
    assert isinstance(out, DrawdownResult)
    assert out.max_drawdown == pytest.approx(-0.25)  # 0.9 / 1.2 - 1
    assert out.peak_date == dates[56]
    assert out.trough_date == dates[57]
    assert out.recovery_date == dates[59]
    assert out.recovered is True
    assert out.observations_used == 60
    assert out.drawdown_series.name == "drawdown"
    assert out.drawdown_series.iloc[57] == pytest.approx(-0.25)
    assert (out.drawdown_series <= 1e-12).all()


def test_episode_without_recovery_in_window() -> None:
    returns = [0.0] * 56 + [0.2, -0.25, 0.0, 0.0]
    dates = _dates(60)
    out = drawdown_analysis(_series(returns))
    assert isinstance(out, DrawdownResult)
    assert out.max_drawdown == pytest.approx(-0.25)
    assert out.peak_date == dates[56]
    assert out.trough_date == dates[57]
    assert out.recovery_date is None
    assert out.recovered is False


def test_monotonic_non_decreasing_series_has_no_episode() -> None:
    out = drawdown_analysis(_series([0.0] * 30 + [0.01] * 30))
    assert isinstance(out, DrawdownResult)
    assert out.max_drawdown == 0.0
    assert out.peak_date is None
    assert out.trough_date is None
    assert out.recovery_date is None
    assert out.recovered is False
    assert (out.drawdown_series == 0.0).all()


def test_below_gate_is_suppressed() -> None:
    out = drawdown_analysis(_series([0.0] * 59))
    assert out == InsufficientObservations("drawdown", 60, 59)


# --------------------------------------------------------------------------- #
# QS-02: the running maximum includes the pre-return anchor wealth of 1.0
# --------------------------------------------------------------------------- #
def test_first_return_is_the_only_loss_is_a_real_drawdown() -> None:
    # A 10% loss on day one, flat afterward: wealth falls from the anchor 1.0
    # to 0.9 and never recovers. Before the fix this reported max_drawdown=0.0
    # because the running max was seeded by wealth[0]=0.9 itself.
    returns = [-0.10] + [0.0] * 59
    out = drawdown_analysis(_series(returns))
    assert isinstance(out, DrawdownResult)
    assert out.max_drawdown == pytest.approx(-0.10)
    assert out.trough_date == _dates(60)[0]
    assert out.recovered is False


def test_two_losses_from_day_one_are_not_understated() -> None:
    # -5% then -5%: true max drawdown is 1 - 0.95*0.95 = -9.75% from the 1.0
    # anchor, not -5% (which is what a running max seeded by wealth[0]=0.95
    # would report - understating the loss by roughly half).
    returns = [-0.05, -0.05] + [0.0] * 58
    out = drawdown_analysis(_series(returns))
    assert isinstance(out, DrawdownResult)
    assert out.max_drawdown == pytest.approx(0.95 * 0.95 - 1.0)


def test_first_return_is_max_drawdown_reports_anchor_date_when_supplied() -> None:
    dates = _dates(60)
    anchor = pd.Timestamp("2023-01-01")  # the price date before dates[0]
    out = drawdown_analysis(_series([-0.10] + [0.0] * 59), anchor_date=anchor)
    assert isinstance(out, DrawdownResult)
    assert out.peak_date == anchor
    assert out.trough_date == dates[0]


def test_first_return_is_max_drawdown_reports_none_without_anchor_date() -> None:
    # No anchor_date supplied: peak_date is None, meaning "the peak precedes
    # the first available return observation" - distinct from the no-episode
    # case, which is also None but paired with max_drawdown == 0.0.
    out = drawdown_analysis(_series([-0.10] + [0.0] * 59))
    assert isinstance(out, DrawdownResult)
    assert out.max_drawdown == pytest.approx(-0.10)
    assert out.peak_date is None


def test_mid_window_peak_is_unaffected_by_the_anchor_fix() -> None:
    # A rally above 1.0 before the trough means the observed peak - not the
    # anchor - governs the drawdown, exactly as before the fix.
    returns = [0.20, -0.05] + [0.0] * 58  # peak at wealth 1.2, trough at 1.14
    dates = _dates(60)
    out = drawdown_analysis(_series(returns), anchor_date=pd.Timestamp("2023-01-01"))
    assert isinstance(out, DrawdownResult)
    assert out.max_drawdown == pytest.approx(-0.05)
    assert out.peak_date == dates[0]
    assert out.trough_date == dates[1]
