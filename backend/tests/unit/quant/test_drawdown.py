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
