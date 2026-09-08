"""Focused unit tests for the Phase 3B factors service helpers (no live
database).

These cover the *plumbing* only - series assembly from ORM rows, the RF / SPY
/ factor-panel loading seams (faked via monkeypatch, not a real session),
result-dataclass -> schema mapping, and the assumptions block. The
statistical correctness of the regressions themselves is covered by the
Phase 3B quant engine unit tests (``tests/unit/quant/test_factors.py``) and is
not re-tested here.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import cast

import exchange_calendars as xcals
import pandas as pd
import pytest
from sqlalchemy.orm import Session

from quantscope.api.factors_schemas import FactorModelResult
from quantscope.db.models import FactorReturn, PriceBar, Security
from quantscope.quant import FactorRegressionResult, InsufficientObservations, UndefinedResult
from quantscope.quant.factors import RegressionCoefficient
from quantscope.services import factors as svc

#: These tests never touch a real database - every DB call is monkeypatched,
#: so a placeholder satisfies the type checker without a real ``Session``.
_SESSION = cast(Session, object())


def _bar(day: str, adj_close: str, close: str = "999.0") -> PriceBar:
    return PriceBar(
        security_id=1,
        trade_date=datetime.date.fromisoformat(day),
        source="tiingo",
        close=Decimal(close),
        adj_close=Decimal(adj_close),
    )


def _xnys_dates(start: str, n: int) -> pd.DatetimeIndex:
    """``n`` genuine, gap-free XNYS sessions from ``start`` - unlike
    ``pd.bdate_range``, which includes US market holidays (QS-01). The real
    service now excludes any return spanning a missing session, so fixtures
    that flow through it must be calendar-continuous to keep their exact
    observation counts meaningful."""
    cal = xcals.get_calendar("XNYS")
    first = cal.date_to_session(start, direction="next")
    return pd.DatetimeIndex(cal.sessions_window(first, n))


def _factor(name: str, day: str, value: str) -> FactorReturn:
    return FactorReturn(
        factor_name=name,
        frequency="daily",
        trade_date=datetime.date.fromisoformat(day),
        source="kenneth_french",
        value=Decimal(value),
    )


# --------------------------------------------------------------------------- #
# Series assembly
# --------------------------------------------------------------------------- #
def test_factor_series_builds_a_named_float_series() -> None:
    rows = [_factor("mkt_rf", "2024-01-02", "0.0012"), _factor("mkt_rf", "2024-01-03", "-0.0005")]
    series = svc._factor_series(rows, "mkt_rf")
    assert series.name == "mkt_rf"
    assert series.dtype == "float64"
    assert list(series) == [0.0012, -0.0005]


def test_load_daily_risk_free_none_when_never_ingested_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(svc, "get_factor_series", lambda session, **kw: [])
    monkeypatch.setattr(svc, "existing_factor_names", lambda session, **kw: set())
    assert svc._load_daily_risk_free(_SESSION, start=None, end=None) is None


def test_load_daily_risk_free_empty_series_when_ingested_but_window_has_no_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # QS-03: rf IS ingested for this source, just not in the requested window.
    monkeypatch.setattr(svc, "get_factor_series", lambda session, **kw: [])
    monkeypatch.setattr(svc, "existing_factor_names", lambda session, **kw: {"rf"})
    series = svc._load_daily_risk_free(_SESSION, start=None, end=None)
    assert series is not None
    assert len(series) == 0


def test_load_daily_risk_free_builds_series_when_rows_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_factor("rf", "2024-01-02", "0.00008")]
    monkeypatch.setattr(svc, "get_factor_series", lambda session, **kw: rows)
    series = svc._load_daily_risk_free(_SESSION, start=None, end=None)
    assert series is not None
    assert list(series) == [0.00008]


def test_load_ff3_factor_panel_groups_by_factor_name(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        _factor("mkt_rf", "2024-01-02", "0.001"),
        _factor("smb", "2024-01-02", "0.0005"),
        _factor("hml", "2024-01-02", "-0.0002"),
        _factor("mkt_rf", "2024-01-03", "0.002"),
    ]
    monkeypatch.setattr(svc, "get_factor_panel", lambda session, **kw: rows)
    panel = svc._load_ff3_factor_panel(_SESSION, start=None, end=None)
    assert set(panel) == {"mkt_rf", "smb", "hml"}
    assert list(panel["mkt_rf"]) == [0.001, 0.002]
    assert list(panel["smb"]) == [0.0005]


def test_load_ff3_factor_panel_always_has_all_three_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    # QS-03: a factor with no rows in the window (but possibly ingested
    # globally) maps to an *empty* Series, not an absent key - the caller
    # uses _globally_missing_ff3_factors, not dict membership, to detect
    # genuine absence.
    rows = [_factor("mkt_rf", "2024-01-02", "0.001"), _factor("smb", "2024-01-02", "0.0005")]
    monkeypatch.setattr(svc, "get_factor_panel", lambda session, **kw: rows)
    panel = svc._load_ff3_factor_panel(_SESSION, start=None, end=None)
    assert set(panel) == {"mkt_rf", "smb", "hml"}
    assert len(panel["hml"]) == 0


def test_globally_missing_ff3_factors_reports_only_never_ingested_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(svc, "existing_factor_names", lambda session, **kw: {"mkt_rf", "smb"})
    assert svc._globally_missing_ff3_factors(_SESSION) == ["hml"]


# --------------------------------------------------------------------------- #
# SPY resolution
# --------------------------------------------------------------------------- #
def test_resolve_spy_returns_unavailable_when_benchmark_security_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(svc, "get_security_by_ticker", lambda session, ticker: None)
    result = svc._resolve_spy_returns(
        _SESSION,
        source="tiingo",
        start=None,
        end=None,
    )
    assert isinstance(result, FactorModelResult)
    assert result.status == "unavailable"
    assert result.reason == "benchmark_security_not_found"


def test_resolve_spy_returns_unavailable_when_benchmark_has_thin_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = Security(id=99, ticker="SPY", name="SPY", exchange="XNAS")
    monkeypatch.setattr(svc, "get_security_by_ticker", lambda session, ticker: spy)
    monkeypatch.setattr(svc, "get_all_price_bars", lambda session, **kw: [_bar("2024-01-02", "10")])
    result = svc._resolve_spy_returns(
        _SESSION,
        source="tiingo",
        start=None,
        end=None,
    )
    assert isinstance(result, FactorModelResult)
    assert result.status == "unavailable"
    assert result.reason == "benchmark_price_history_unavailable"


def test_resolve_spy_returns_insufficient_not_unavailable_when_only_adjacency_is_gapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SPY-01: SPY has >= 2 bars, but its one possible adjacency spans a
    # missing XNYS session - price history is not missing, so this must be
    # `insufficient_observations` (observed 0), never `unavailable`.
    spy = Security(id=99, ticker="SPY", name="SPY", exchange="XNAS")
    spy_bars = [_bar("2024-01-02", "400"), _bar("2024-01-04", "401")]  # Tue, Thu - Wed missing
    monkeypatch.setattr(svc, "get_security_by_ticker", lambda session, ticker: spy)
    monkeypatch.setattr(svc, "get_all_price_bars", lambda session, **kw: spy_bars)
    result = svc._resolve_spy_returns(
        _SESSION,
        source="tiingo",
        start=None,
        end=None,
    )
    assert isinstance(result, FactorModelResult)
    assert result.status == "insufficient_observations"
    assert result.observations_used == 0
    assert result.required == svc.MIN_OBS_CAPM_REGRESSION
    assert result.reason is None


def test_resolve_spy_returns_ok_when_history_present(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = _xnys_dates("2023-01-02", 5)
    spy = Security(id=99, ticker="SPY", name="SPY", exchange="XNAS")
    spy_bars = [_bar(str(d.date()), str(100.0 + i)) for i, d in enumerate(dates)]
    monkeypatch.setattr(svc, "get_security_by_ticker", lambda session, ticker: spy)
    monkeypatch.setattr(svc, "get_all_price_bars", lambda session, **kw: spy_bars)
    result = svc._resolve_spy_returns(
        _SESSION,
        source="tiingo",
        start=None,
        end=None,
    )
    assert not isinstance(result, FactorModelResult)
    assert len(result) == 4


# --------------------------------------------------------------------------- #
# Result mapping
# --------------------------------------------------------------------------- #
def test_map_regression_result_insufficient_observations() -> None:
    mapped = svc._map_regression_result(InsufficientObservations("capm_regression", 126, 80))
    assert mapped.status == "insufficient_observations"
    assert mapped.required == 126
    assert mapped.observations_used == 80
    assert mapped.coefficients is None


def test_map_regression_result_undefined() -> None:
    mapped = svc._map_regression_result(
        UndefinedResult("ff3_regression", "regressor 'smb' has zero variance", 260)
    )
    assert mapped.status == "undefined"
    assert mapped.reason == "regressor 'smb' has zero variance"
    assert mapped.observations_used == 260


def test_map_regression_result_ok() -> None:
    result = FactorRegressionResult(
        model="capm_regression",
        observations_used=200,
        aligned_start=pd.Timestamp("2023-01-02"),
        aligned_end=pd.Timestamp("2023-10-10"),
        coefficients=(
            RegressionCoefficient("alpha", 0.0001, 0.00005, 2.0, 0.04, 0.00001, 0.00019),
            RegressionCoefficient("spy_excess", 1.2, 0.1, 12.0, 0.0, 1.0, 1.4),
        ),
        r_squared=0.65,
        adjusted_r_squared=0.64,
        hac_lags=4,
    )
    mapped = svc._map_regression_result(result)
    assert mapped.status == "ok"
    assert mapped.aligned_start == datetime.date(2023, 1, 2)
    assert mapped.aligned_end == datetime.date(2023, 10, 10)
    assert mapped.coefficients is not None
    assert [c.name for c in mapped.coefficients] == ["alpha", "spy_excess"]
    assert mapped.coefficients[1].estimate == 1.2
    assert mapped.r_squared == 0.65
    assert mapped.hac_lags == 4


# --------------------------------------------------------------------------- #
# compute_ticker_factors orchestration
# --------------------------------------------------------------------------- #
def test_compute_ticker_factors_both_unavailable_when_price_history_too_thin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(svc, "get_all_price_bars", lambda session, **kw: [_bar("2024-01-02", "10")])
    # RF is now checked unconditionally, even though price history is thin
    # (QS-03) - mock it minimally so the call does not hit a real database.
    monkeypatch.setattr(svc, "get_factor_series", lambda session, **kw: [])
    monkeypatch.setattr(svc, "existing_factor_names", lambda session, **kw: set())
    security = Security(id=1, ticker="NVDA", name="NVIDIA", exchange="XNAS")
    response = svc.compute_ticker_factors(
        _SESSION,
        security=security,
        source="tiingo",
        start=None,
        end=None,
    )
    assert response.capm.status == "unavailable"
    assert response.capm.reason == "asset_price_history_unavailable"
    assert response.ff3.status == "unavailable"
    assert response.ff3.reason == "asset_price_history_unavailable"
    # RF was genuinely never ingested here either.
    assert response.assumptions.rf_source == "not_ingested"


def test_compute_ticker_factors_thin_price_history_still_reports_rf_truthfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # QS-03 (Part B): RF IS ingested, but the asset's own price history is too
    # thin to compute either model. assumptions.rf_source must reflect that RF
    # was actually checked and found - never "not_ingested" merely because the
    # *asset* has too little history.
    monkeypatch.setattr(svc, "get_all_price_bars", lambda session, **kw: [_bar("2024-01-02", "10")])
    monkeypatch.setattr(
        svc, "get_factor_series", lambda session, **kw: [_factor("rf", "2024-01-02", "0.00003")]
    )
    security = Security(id=1, ticker="NVDA", name="NVIDIA", exchange="XNAS")
    response = svc.compute_ticker_factors(
        _SESSION, security=security, source="tiingo", start=None, end=None
    )
    assert response.capm.status == "unavailable"
    assert response.capm.reason == "asset_price_history_unavailable"
    assert response.assumptions.rf_source == "kenneth_french_daily"


def test_compute_ticker_factors_both_insufficient_when_all_adjacencies_gapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # RA-03 (was QS-01's empty-series guard): exactly 2 price bars whose one
    # possible adjacency spans a missing XNYS session - an empty gap-filtered
    # return series despite >= 2 bars actually being persisted. Price history
    # is not missing, so this must not claim "unavailable" - it is reported
    # the same way services.analytics reports the identical situation for its
    # own return series: insufficient_observations, observed = 0. Never a
    # crash from feeding an empty series into capm_regression/ff3_regression.
    price_bars = [_bar("2024-01-02", "100"), _bar("2024-01-04", "101")]  # Tue, Thu - Wed missing
    monkeypatch.setattr(svc, "get_all_price_bars", lambda session, **kw: price_bars)
    monkeypatch.setattr(
        svc, "get_factor_series", lambda session, **kw: [_factor("rf", "2024-01-02", "0.00003")]
    )
    security = Security(id=1, ticker="NVDA", name="NVIDIA", exchange="XNAS")
    response = svc.compute_ticker_factors(
        _SESSION, security=security, source="tiingo", start=None, end=None
    )
    assert response.capm.status == "insufficient_observations"
    assert response.capm.observations_used == 0
    assert response.capm.required == svc.MIN_OBS_CAPM_REGRESSION
    assert response.ff3.status == "insufficient_observations"
    assert response.ff3.observations_used == 0
    assert response.ff3.required == svc.MIN_OBS_FF3_REGRESSION


def test_compute_ticker_factors_both_insufficient_when_rf_ingested_but_window_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = _xnys_dates("2023-01-02", 130)
    price_bars = [_bar(str(d.date()), str(100.0 + i * 0.1)) for i, d in enumerate(dates)]
    monkeypatch.setattr(svc, "get_all_price_bars", lambda session, **kw: price_bars)
    # rf is ingested for this source, just not in the requested window.
    monkeypatch.setattr(svc, "get_factor_series", lambda session, **kw: [])
    monkeypatch.setattr(svc, "existing_factor_names", lambda session, **kw: {"rf"})

    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("should not query SPY/factors when the rf window is empty")

    monkeypatch.setattr(svc, "get_security_by_ticker", _boom)
    monkeypatch.setattr(svc, "get_factor_panel", _boom)

    security = Security(id=1, ticker="NVDA", name="NVIDIA", exchange="XNAS")
    response = svc.compute_ticker_factors(
        _SESSION, security=security, source="tiingo", start=None, end=None
    )
    assert response.capm.status == "insufficient_observations"
    assert response.capm.required == 126
    assert response.capm.observations_used == 0
    assert response.ff3.status == "insufficient_observations"
    assert response.ff3.required == 250
    assert response.ff3.observations_used == 0
    assert response.assumptions.rf_source == "kenneth_french_daily"


def test_compute_ticker_factors_both_unavailable_when_rf_missing_and_never_queries_spy_or_factors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = _xnys_dates("2023-01-02", 130)
    price_bars = [_bar(str(d.date()), str(100.0 + i * 0.1)) for i, d in enumerate(dates)]

    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("should not query SPY/factors when RF is absent")

    monkeypatch.setattr(svc, "get_all_price_bars", lambda session, **kw: price_bars)
    monkeypatch.setattr(svc, "get_factor_series", lambda session, **kw: [])
    monkeypatch.setattr(svc, "existing_factor_names", lambda session, **kw: set())
    monkeypatch.setattr(svc, "get_security_by_ticker", _boom)
    monkeypatch.setattr(svc, "get_factor_panel", _boom)

    security = Security(id=1, ticker="NVDA", name="NVIDIA", exchange="XNAS")
    response = svc.compute_ticker_factors(
        _SESSION,
        security=security,
        source="tiingo",
        start=None,
        end=None,
    )
    assert response.capm.status == "unavailable"
    assert response.capm.reason == "risk_free_series_not_ingested"
    assert response.ff3.status == "unavailable"
    assert response.ff3.reason == "risk_free_series_not_ingested"
    assert response.assumptions.rf_source == "not_ingested"


def test_compute_ticker_factors_ff3_unavailable_when_one_factor_missing_capm_unaffected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = _xnys_dates("2023-01-02", 130)
    price_bars = [_bar(str(d.date()), str(100.0 + i * 0.1)) for i, d in enumerate(dates)]
    rf_rows = [_factor("rf", str(d.date()), "0.00003") for d in dates]
    spy = Security(id=99, ticker="SPY", name="SPY", exchange="XNAS")
    spy_bars = [_bar(str(d.date()), str(200.0 + i * 0.2)) for i, d in enumerate(dates)]
    factor_rows = [_factor("mkt_rf", str(d.date()), "0.0004") for d in dates] + [
        _factor("smb", str(d.date()), "0.0001") for d in dates
    ]  # hml never ingested

    monkeypatch.setattr(
        svc,
        "get_all_price_bars",
        lambda session, security_id, **kw: (spy_bars if security_id == 99 else price_bars),
    )
    monkeypatch.setattr(svc, "get_factor_series", lambda session, **kw: rf_rows)
    monkeypatch.setattr(svc, "get_security_by_ticker", lambda session, ticker: spy)
    monkeypatch.setattr(svc, "get_factor_panel", lambda session, **kw: factor_rows)
    # hml was never ingested for this source at all (not merely absent from
    # this window) - the other two FF3 factors were.
    monkeypatch.setattr(svc, "existing_factor_names", lambda session, **kw: {"mkt_rf", "smb"})

    security = Security(id=1, ticker="NVDA", name="NVIDIA", exchange="XNAS")
    response = svc.compute_ticker_factors(
        _SESSION,
        security=security,
        source="tiingo",
        start=None,
        end=None,
    )
    assert response.capm.status == "ok"
    assert response.ff3.status == "unavailable"
    assert response.ff3.reason == "factor_not_ingested:hml"


def test_compute_ticker_factors_full_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = _xnys_dates("2023-01-02", 260)
    pattern = [0.01, -0.008, 0.006, -0.011, 0.009]
    asset_path = [100.0]
    for i in range(1, 260):
        asset_path.append(asset_path[-1] * (1.0 + pattern[(i - 1) % len(pattern)]))
    price_bars = [_bar(str(d.date()), str(v)) for d, v in zip(dates, asset_path, strict=True)]

    spy_pattern = [0.004, -0.002, 0.003, -0.005, 0.0025]
    spy_path = [200.0]
    for i in range(1, 260):
        spy_path.append(spy_path[-1] * (1.0 + spy_pattern[(i - 1) % len(spy_pattern)]))
    spy = Security(id=99, ticker="SPY", name="SPY", exchange="XNAS")
    spy_bars = [_bar(str(d.date()), str(v)) for d, v in zip(dates, spy_path, strict=True)]

    rf_rows = [_factor("rf", str(d.date()), "0.00003") for d in dates]
    mkt_pattern = [0.0004, -0.0003, 0.0005, -0.0002, 0.0003]
    smb_pattern = [0.0001, -0.0002, 0.0003, -0.0001, 0.0002]
    hml_pattern = [-0.0002, 0.0001, -0.0003, 0.0002, -0.0001]
    factor_rows = (
        [_factor("mkt_rf", str(d.date()), str(mkt_pattern[i % 5])) for i, d in enumerate(dates)]
        + [_factor("smb", str(d.date()), str(smb_pattern[i % 5])) for i, d in enumerate(dates)]
        + [_factor("hml", str(d.date()), str(hml_pattern[i % 5])) for i, d in enumerate(dates)]
    )

    monkeypatch.setattr(
        svc,
        "get_all_price_bars",
        lambda session, security_id, **kw: (spy_bars if security_id == 99 else price_bars),
    )
    monkeypatch.setattr(svc, "get_factor_series", lambda session, **kw: rf_rows)
    monkeypatch.setattr(svc, "get_security_by_ticker", lambda session, ticker: spy)
    monkeypatch.setattr(svc, "get_factor_panel", lambda session, **kw: factor_rows)
    monkeypatch.setattr(
        svc, "existing_factor_names", lambda session, **kw: {"mkt_rf", "smb", "hml"}
    )

    security = Security(id=1, ticker="NVDA", name="NVIDIA", exchange="XNAS")
    response = svc.compute_ticker_factors(
        _SESSION,
        security=security,
        source="tiingo",
        start=None,
        end=None,
    )
    assert response.capm.status == "ok"
    assert response.ff3.status == "ok"
    assert response.capm.coefficients is not None and response.ff3.coefficients is not None
    assert [c.name for c in response.capm.coefficients] == ["alpha", "spy_excess"]
    assert [c.name for c in response.ff3.coefficients] == ["alpha", "mkt_rf", "smb", "hml"]
    assert response.assumptions.rf_source == "kenneth_french_daily"
    assert "different quantities" in response.assumptions.capm_vs_ff3_note
    assert "not annualized" in response.assumptions.alpha_note
    assert response.assumptions.min_observations == {"capm_regression": 126, "ff3_regression": 250}
