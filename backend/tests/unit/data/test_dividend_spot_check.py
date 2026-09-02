"""`verify_dividend_back_adjustment` - synthetic dividend / split-only cases."""

from __future__ import annotations

from quantscope.data.spot_checks import verify_dividend_back_adjustment


def test_crsp_dividend_adjusted_series_is_total_return() -> None:
    # Constructed CRSP back-adjustment: factor before ex = (1 - D/close_before).
    close_before, dividend = 100.0, 2.0
    close_ex = 99.0
    factor = 1.0 - dividend / close_before  # 0.98
    adj_close_ex = close_ex  # no later corporate actions in this toy series
    adj_close_before = close_before * factor  # 98.0

    r = verify_dividend_back_adjustment(
        close_before=close_before,
        close_ex=close_ex,
        adj_close_before=adj_close_before,
        adj_close_ex=adj_close_ex,
        dividend=dividend,
    )
    assert r.passed is True
    assert r.dividend_incorporated is True
    assert abs(r.implied_dividend - dividend) <= 0.10 * dividend
    # adjusted total return exceeds the raw price drop by ~the dividend yield
    assert r.adj_total_return > r.raw_price_return


def test_split_only_series_flagged_as_not_total_return() -> None:
    # Adjusted == split-only: adjusted return equals raw price return.
    close_before, close_ex, dividend = 100.0, 99.0, 2.0
    r = verify_dividend_back_adjustment(
        close_before=close_before,
        close_ex=close_ex,
        adj_close_before=close_before,  # no dividend folded in
        adj_close_ex=close_ex,
        dividend=dividend,
    )
    assert r.passed is False
    assert r.dividend_incorporated is False
    assert abs(r.implied_dividend) < 0.10 * dividend  # ~0
    assert any("UNDERSTATE total return" in o for o in r.observations)


def test_realistic_small_dividend_still_distinguishable() -> None:
    # AAPL-scale: ~0.14% quarterly yield is well below any return tolerance,
    # but the implied-dividend check still resolves it.
    close_before, dividend = 183.0, 0.25
    close_ex = 181.4
    adj_close_before = close_before - dividend  # CRSP factor form
    adj_close_ex = close_ex

    r = verify_dividend_back_adjustment(
        close_before=close_before,
        close_ex=close_ex,
        adj_close_before=adj_close_before,
        adj_close_ex=adj_close_ex,
        dividend=dividend,
    )
    assert r.dividend_incorporated is True
    assert abs(r.implied_dividend - dividend) <= 0.01


def test_step_with_split_is_rejected_as_not_a_clean_dividend_test() -> None:
    r = verify_dividend_back_adjustment(
        close_before=100.0,
        close_ex=50.0,
        adj_close_before=100.0,
        adj_close_ex=100.0,
        dividend=1.0,
        split_factor_ex=2.0,
    )
    assert r.passed is False
    assert any("split" in o for o in r.observations)


def test_non_ex_dividend_step_is_rejected() -> None:
    r = verify_dividend_back_adjustment(
        close_before=100.0,
        close_ex=101.0,
        adj_close_before=100.0,
        adj_close_ex=101.0,
        dividend=0.0,
    )
    assert r.passed is False
    assert any("not an ex-dividend step" in o for o in r.observations)
