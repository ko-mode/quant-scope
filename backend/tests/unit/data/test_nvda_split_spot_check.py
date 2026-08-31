"""NVDA 10-for-1 split spot-check against hand-authored fixtures."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from quantscope.data.prices import normalize_price_bars
from quantscope.data.providers.stooq import parse_stooq_csv
from quantscope.data.spot_checks import check_nvda_split_adjustment

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "prices"


def _frame(name: str) -> pd.DataFrame:
    bars = parse_stooq_csv((_FIXTURES / name).read_text())
    return normalize_price_bars(bars, source="stooq").frame


def test_split_adjusted_series_passes() -> None:
    result = check_nvda_split_adjustment(_frame("nvda_split_adjusted.csv"))
    assert result.passed is True
    assert result.ratio_across_split is not None
    assert 0.9 <= result.ratio_across_split <= 1.1
    assert any("no ~10x discontinuity" in o for o in result.observations)


def test_unadjusted_series_fails_with_discontinuity() -> None:
    result = check_nvda_split_adjustment(_frame("nvda_split_unadjusted.csv"))
    assert result.passed is False
    assert result.ratio_across_split is not None
    assert result.ratio_across_split > 5
    assert any("DISCONTINUITY" in o for o in result.observations)


def test_frame_not_covering_split_window_fails_clearly() -> None:
    frame = _frame("nvda_split_adjusted.csv")
    truncated = frame[frame["trade_date"] < "2024-06-01"]
    result = check_nvda_split_adjustment(truncated)
    assert result.passed is False
    assert any("does not cover" in o for o in result.observations)
