"""Multi-security comparison: one common inner-joined return panel, normalized
performance and Pearson correlation (ADR 0017 "Multi-security comparison").

Golden values are computed by hand or via a small independent script, not by
comparing pandas output against itself.
"""

from __future__ import annotations

import pandas as pd
import pytest

from quantscope.quant.comparison import ComparisonPanel, compare_securities
from quantscope.quant.results import InsufficientObservations, QuantInputError


def _dates(start: str, n: int) -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=n)


def _series(dates: pd.DatetimeIndex, values: list[float]) -> pd.Series:
    return pd.Series(values, index=dates, dtype="float64")


def _flat(start: str, n: int, value: float) -> pd.Series:
    return _series(_dates(start, n), [value] * n)


# --------------------------------------------------------------------------- #
# Structural validation (reuses validate_return_series - "consistent with
# existing quant rules", no bespoke handling in the comparison module).
# --------------------------------------------------------------------------- #
def test_fewer_than_two_series_is_a_quant_input_error() -> None:
    with pytest.raises(QuantInputError, match="at least two securities"):
        compare_securities({"AAPL": _flat("2023-01-02", 80, 0.01)})


def test_unsorted_return_series_is_rejected() -> None:
    dates = _dates("2023-01-02", 80)[::-1]  # descending
    bad = _series(dates, [0.01] * 80)
    with pytest.raises(QuantInputError, match="sorted ascending"):
        compare_securities({"AAPL": bad, "MSFT": _flat("2023-01-02", 80, 0.01)})


def test_duplicate_date_return_series_is_rejected() -> None:
    dates = pd.DatetimeIndex(["2023-01-02", "2023-01-02", "2023-01-03"])
    bad = _series(dates, [0.01, 0.02, 0.01])
    with pytest.raises(QuantInputError, match="duplicate dates"):
        compare_securities({"AAPL": bad, "MSFT": _flat("2023-01-02", 3, 0.01)})


# --------------------------------------------------------------------------- #
# Alignment: the inner join selects exactly the true common dates.
# --------------------------------------------------------------------------- #
def test_ragged_three_asset_join_counts_only_the_true_common_dates() -> None:
    # Mirrors the worked A,B,C,D,E example: AAPL has all 5 dates, MSFT is
    # missing the last one (E), NVDA is missing the first one (A). The true
    # common panel is exactly {B, C, D} = 3 dates - below the 60-gate, so this
    # asserts the *count* the alignment produced (the proof of "which dates"
    # survives at full scale in the next test).
    all_dates = _dates("2024-01-02", 5)  # A, B, C, D, E
    aapl = _series(all_dates, [0.01, 0.02, -0.01, 0.03, 0.01])
    msft = _series(all_dates[:4], [0.02, -0.01, 0.02, 0.01])  # A,B,C,D
    nvda = _series(all_dates[1:], [0.03, -0.02, 0.01, 0.02])  # B,C,D,E

    result = compare_securities({"AAPL": aapl, "MSFT": msft, "NVDA": nvda})
    assert result == InsufficientObservations("comparison", 60, 3)


def test_alignment_selects_exactly_the_true_intersection_at_full_scale() -> None:
    # 70 trading days. AAPL covers all 70. MSFT is missing the first 3 (starts
    # late). NVDA is missing the last 3 (ends early). The true common panel is
    # positions [3, 66] inclusive = 64 dates - neither the AAPL/MSFT overlap
    # (67) nor the AAPL/NVDA overlap (67) nor the full 70, proving the engine
    # used the actual 3-way intersection, not a pairwise one.
    dates = _dates("2023-01-02", 70)
    pattern = [0.01, -0.008, 0.006, -0.011, 0.009, 0.004, -0.013, 0.012]
    values = (pattern * (70 // len(pattern) + 1))[:70]

    aapl = _series(dates, values)
    msft = _series(dates[3:], values[3:])
    nvda = _series(dates[:67], values[:67])

    result = compare_securities({"AAPL": aapl, "MSFT": msft, "NVDA": nvda})
    assert isinstance(result, ComparisonPanel)
    assert result.observations_used == 64
    assert result.aligned_start == dates[3]
    assert result.aligned_end == dates[66]
    assert list(result.returns.index) == list(dates[3:67])


def test_no_common_dates_is_the_zero_observation_case_of_insufficient() -> None:
    # Two entirely disjoint calendars: the intersection is empty by
    # construction, which is just observations_used == 0 on the same gate -
    # no special-casing needed.
    a = _flat("2023-01-02", 80, 0.01)
    b = _flat("2027-01-04", 80, 0.01)
    result = compare_securities({"AAPL": a, "MSFT": b})
    assert result == InsufficientObservations("comparison", 60, 0)


def test_below_gate_but_nonzero_overlap_is_insufficient() -> None:
    dates = _dates("2023-01-02", 65)
    a = _series(dates, [0.01] * 65)
    b = _series(dates[60:], [0.01] * 5)  # only 5 dates in common
    result = compare_securities({"AAPL": a, "MSFT": b})
    assert result == InsufficientObservations("comparison", 60, 5)


def test_all_output_series_share_identical_dates() -> None:
    dates = _dates("2023-01-02", 60)
    pattern = [0.01, -0.008, 0.006, -0.011, 0.009, 0.004, -0.013, 0.012]
    values = (pattern * (60 // len(pattern) + 1))[:60]
    a = _series(dates, values)
    b = _series(dates, [v * 0.5 for v in values])

    result = compare_securities({"AAPL": a, "MSFT": b})
    assert isinstance(result, ComparisonPanel)
    assert list(result.returns.index) == list(dates)
    # normalized_performance is the return panel's dates plus one leading
    # anchor row (NaT) - same underlying date set, nothing extra invented.
    assert list(result.normalized_performance.index[1:]) == list(dates)
    assert pd.isna(result.normalized_performance.index[0])


# --------------------------------------------------------------------------- #
# Normalized performance: every return preserved, none divided away.
# --------------------------------------------------------------------------- #
def test_normalized_performance_anchor_is_100_with_no_date() -> None:
    dates = _dates("2023-01-02", 60)
    a = _series(dates, [0.05] + [0.0] * 59)
    b = _series(dates, [-0.03] + [0.0] * 59)

    result = compare_securities({"AAPL": a, "MSFT": b})
    assert isinstance(result, ComparisonPanel)
    norm = result.normalized_performance
    assert len(norm) == 61  # observations_used (60) + 1 anchor row
    assert pd.isna(norm.index[0])
    assert norm.iloc[0]["AAPL"] == pytest.approx(100.0)
    assert norm.iloc[0]["MSFT"] == pytest.approx(100.0)


def test_first_aligned_return_is_preserved_not_divided_away() -> None:
    # The rejected design (100 * growth / growth.iloc[0]) would cancel the
    # first return and force row 1 back to exactly 100. This proves it is NOT
    # cancelled: row 1 must reflect the full +5% / -3% first-day move.
    dates = _dates("2023-01-02", 60)
    a = _series(dates, [0.05] + [0.0] * 59)
    b = _series(dates, [-0.03] + [0.0] * 59)

    result = compare_securities({"AAPL": a, "MSFT": b})
    assert isinstance(result, ComparisonPanel)
    norm = result.normalized_performance
    assert norm.iloc[1]["AAPL"] == pytest.approx(105.0)
    assert norm.iloc[1]["MSFT"] == pytest.approx(97.0)
    assert norm.iloc[1]["AAPL"] != pytest.approx(100.0)
    # flat thereafter (all remaining returns are 0), including the last row
    assert norm.iloc[-1]["AAPL"] == pytest.approx(105.0)
    assert norm.iloc[-1]["MSFT"] == pytest.approx(97.0)


def test_normalized_performance_compounds_every_return_in_sequence() -> None:
    dates = _dates("2023-01-02", 60)
    rets = [0.05, -0.02, 0.03] + [0.0] * 57
    a = _series(dates, rets)

    result = compare_securities({"AAPL": a, "MSFT": _flat("2023-01-02", 60, 0.0)})
    assert isinstance(result, ComparisonPanel)
    norm = result.normalized_performance["AAPL"]
    assert norm.iloc[0] == pytest.approx(100.0)
    assert norm.iloc[1] == pytest.approx(100 * 1.05)
    assert norm.iloc[2] == pytest.approx(100 * 1.05 * 0.98)
    assert norm.iloc[3] == pytest.approx(100 * 1.05 * 0.98 * 1.03)


# --------------------------------------------------------------------------- #
# Correlation
# --------------------------------------------------------------------------- #
def test_pearson_correlation_matches_a_hand_computed_value() -> None:
    # r = sum(dx*dy) / sqrt(sum(dx^2) * sum(dy^2)) computed by hand for the
    # 5-pair pattern below: mean(X)=mean(Y)=0.006,
    # sum(dx*dy)=0.00132, sum(dx^2)=sum(dy^2)=0.00172 -> r = 0.767441860...
    # Pearson r is invariant under exact repetition of the same paired
    # pattern (mean/covariance/variance all scale by the same tile count and
    # cancel in the ratio), so tiling 12x to clear the 60-observation gate
    # does not change the expected value.
    x_pattern = [0.01, -0.02, 0.03, -0.01, 0.02]
    y_pattern = [0.02, -0.01, 0.01, -0.02, 0.03]
    dates = _dates("2023-01-02", 60)
    x = _series(dates, x_pattern * 12)
    y = _series(dates, y_pattern * 12)

    result = compare_securities({"X": x, "Y": y})
    assert isinstance(result, ComparisonPanel)
    assert result.correlation.loc["X", "Y"] == pytest.approx(0.7674418604651162)
    assert result.correlation.loc["Y", "X"] == pytest.approx(0.7674418604651162)


def test_correlation_matrix_is_symmetric_with_unit_diagonal() -> None:
    dates = _dates("2023-01-02", 60)
    pattern = [0.01, -0.008, 0.006, -0.011, 0.009, 0.004, -0.013, 0.012]
    values = (pattern * (60 // len(pattern) + 1))[:60]
    a = _series(dates, values)
    b = _series(dates, [v * -0.5 + 0.001 for v in values])
    c = _series(dates, [v * 2.0 - 0.002 for v in values])

    result = compare_securities({"AAPL": a, "MSFT": b, "NVDA": c})
    assert isinstance(result, ComparisonPanel)
    corr = result.correlation
    assert corr.to_numpy() == pytest.approx(corr.to_numpy().T)
    for ticker in ("AAPL", "MSFT", "NVDA"):
        assert corr.loc[ticker, ticker] == pytest.approx(1.0)


def test_no_pairwise_complete_leakage() -> None:
    # AAPL and MSFT are IDENTICAL over the first 65 dates (r == 1.0 there) but
    # deliberately diverge over the last 5. NVDA only has data for the first
    # 65 dates, so the true 3-way common panel is exactly those 65 dates. If
    # the engine leaked into pairwise-complete correlation for AAPL/MSFT (all
    # 70 of *their* common dates, ignoring NVDA's shorter coverage), the
    # divergence in the last 5 dates would pull corr(AAPL, MSFT) below 1.0.
    dates = _dates("2023-01-02", 70)
    pattern = [0.01, -0.008, 0.006, -0.011, 0.009, 0.004, -0.013, 0.012]
    base = (pattern * (70 // len(pattern) + 1))[:70]

    aapl = _series(dates, base)
    msft_values = base[:65] + [-v for v in base[65:]]  # diverges only after date 65
    msft = _series(dates, msft_values)
    nvda = _series(dates[:65], base[:65])

    result = compare_securities({"AAPL": aapl, "MSFT": msft, "NVDA": nvda})
    assert isinstance(result, ComparisonPanel)
    assert result.observations_used == 65
    assert result.correlation.loc["AAPL", "MSFT"] == pytest.approx(1.0)


def test_constant_return_ticker_is_undefined_not_zero_and_does_not_affect_others() -> None:
    dates = _dates("2023-01-02", 60)
    pattern = [0.01, -0.008, 0.006, -0.011, 0.009, 0.004, -0.013, 0.012]
    values = (pattern * (60 // len(pattern) + 1))[:60]
    a = _series(dates, values)
    b = _series(dates, [v * -1.3 + 0.0005 for v in values])
    flat = _series(dates, [0.0] * 60)

    result = compare_securities({"AAPL": a, "MSFT": b, "FLAT": flat})
    assert isinstance(result, ComparisonPanel)
    assert result.zero_variance_tickers == ("FLAT",)

    corr = result.correlation
    assert pd.isna(corr.loc["FLAT", "FLAT"])  # 0/0, not 1.0
    assert pd.isna(corr.loc["FLAT", "AAPL"])
    assert pd.isna(corr.loc["AAPL", "FLAT"])
    # unrelated pair is entirely unaffected by FLAT's presence
    assert not pd.isna(corr.loc["AAPL", "MSFT"])
    assert corr.loc["AAPL", "MSFT"] == pytest.approx(-1.0)
