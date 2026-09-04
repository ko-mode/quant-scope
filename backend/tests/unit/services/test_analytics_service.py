"""Focused unit tests for the analytics service helpers (no live database).

These cover the *plumbing* only - series assembly from ORM rows, the RF /
SPY loading seams (faked via monkeypatch, not a real session), dataclass ->
schema mapping, and the assumptions block. The statistical correctness of the
metrics themselves is already covered by the Phase 2A engine unit tests and is
not re-tested here.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pandas as pd
import pytest

from quantscope.db.models import FactorReturn, PriceBar, Security
from quantscope.quant import (
    BetaResult,
    DrawdownResult,
    HistoricalVarEsResult,
    InsufficientObservations,
    ReturnSummary,
    SharpeResult,
    UndefinedResult,
)
from quantscope.services import analytics as svc


def _bar(day: str, adj_close: str, close: str = "999.0") -> PriceBar:
    return PriceBar(
        security_id=1,
        trade_date=datetime.date.fromisoformat(day),
        source="tiingo",
        close=Decimal(close),
        adj_close=Decimal(adj_close),
    )


def _factor(day: str, value: str) -> FactorReturn:
    return FactorReturn(
        factor_name="rf",
        frequency="daily",
        trade_date=datetime.date.fromisoformat(day),
        source="kenneth_french",
        value=Decimal(value),
    )


def test_adjusted_close_series_uses_adj_close_not_raw_close() -> None:
    bars = [_bar("2024-01-02", "95.20", close="100.10"), _bar("2024-01-03", "96.00", close="101.0")]
    series = svc._adjusted_close_series(bars)

    assert isinstance(series.index, pd.DatetimeIndex)
    assert list(series) == [95.20, 96.00]  # adj_close, not close
    assert series.dtype == "float64"
    assert list(series.index) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]


def test_risk_free_series_builds_a_named_float_series() -> None:
    rows = [_factor("2024-01-02", "0.00008"), _factor("2024-01-03", "0.00009")]
    series = svc._risk_free_series(rows)
    assert series.name == "rf"
    assert series.dtype == "float64"
    assert list(series) == [0.00008, 0.00009]


def test_load_daily_risk_free_none_when_nothing_persisted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "get_factor_series", lambda session, **kw: [])
    assert svc._load_daily_risk_free(object(), start=None, end=None) is None  # type: ignore[arg-type]


def test_load_daily_risk_free_builds_series_when_rows_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_factor("2024-01-02", "0.00008")]
    monkeypatch.setattr(svc, "get_factor_series", lambda session, **kw: rows)
    series = svc._load_daily_risk_free(object(), start=None, end=None)  # type: ignore[arg-type]
    assert series is not None
    assert list(series) == [0.00008]


def test_compute_sharpe_is_unavailable_when_rf_is_none() -> None:
    returns = pd.Series([0.01] * 130, index=pd.bdate_range("2023-01-02", periods=130))
    metric = svc._compute_sharpe(returns, None)
    assert metric.status == "unavailable"
    assert metric.reason == "risk_free_series_not_ingested"


def test_compute_sharpe_delegates_to_the_engine_when_rf_present() -> None:
    dates = pd.bdate_range("2023-01-02", periods=130)
    returns = pd.Series([0.0] * 129 + [0.1], index=dates)
    rf = pd.Series(0.0, index=dates)
    metric = svc._compute_sharpe(returns, rf)
    assert metric.status == "ok"
    assert metric.risk_free_basis == "daily_series"


def test_compute_beta_is_unavailable_when_rf_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def _boom(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("should not query SPY when RF is absent")

    monkeypatch.setattr(svc, "get_security_by_ticker", _boom)
    returns = pd.Series([0.01] * 130, index=pd.bdate_range("2023-01-02", periods=130))
    metric = svc._compute_beta(
        object(),  # type: ignore[arg-type]
        asset_returns=returns,
        source="tiingo",
        start=None,
        end=None,
        rf=None,
    )
    assert metric.status == "unavailable"
    assert metric.reason == "risk_free_series_not_ingested"
    assert not called


def test_compute_beta_is_unavailable_when_benchmark_security_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(svc, "get_security_by_ticker", lambda session, ticker: None)
    dates = pd.bdate_range("2023-01-02", periods=130)
    returns = pd.Series([0.01] * 130, index=dates)
    rf = pd.Series(0.0, index=dates)
    metric = svc._compute_beta(
        object(),  # type: ignore[arg-type]
        asset_returns=returns,
        source="tiingo",
        start=None,
        end=None,
        rf=rf,
    )
    assert metric.status == "unavailable"
    assert metric.reason == "benchmark_security_not_found"


def test_compute_beta_is_unavailable_when_benchmark_has_thin_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = Security(id=99, ticker="SPY", name="SPY", exchange="XNAS")
    monkeypatch.setattr(svc, "get_security_by_ticker", lambda session, ticker: spy)
    monkeypatch.setattr(svc, "get_all_price_bars", lambda session, **kw: [_bar("2024-01-02", "10")])
    dates = pd.bdate_range("2023-01-02", periods=130)
    returns = pd.Series([0.01] * 130, index=dates)
    rf = pd.Series(0.0, index=dates)
    metric = svc._compute_beta(
        object(),  # type: ignore[arg-type]
        asset_returns=returns,
        source="tiingo",
        start=None,
        end=None,
        rf=rf,
    )
    assert metric.status == "unavailable"
    assert metric.reason == "benchmark_price_history_unavailable"


def test_compute_beta_delegates_to_the_engine_when_everything_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = pd.bdate_range("2023-01-02", periods=130)
    spy = Security(id=99, ticker="SPY", name="SPY", exchange="XNAS")
    spy_bars = [_bar(str(d.date()), str(100.0 + i * 0.1)) for i, d in enumerate(dates)]
    monkeypatch.setattr(svc, "get_security_by_ticker", lambda session, ticker: spy)
    monkeypatch.setattr(svc, "get_all_price_bars", lambda session, **kw: spy_bars)

    returns = pd.Series([0.01, -0.005] * 65, index=dates)
    rf = pd.Series(0.0, index=dates)
    metric = svc._compute_beta(
        object(),  # type: ignore[arg-type]
        asset_returns=returns,
        source="tiingo",
        start=None,
        end=None,
        rf=rf,
    )
    assert metric.status == "ok"
    assert metric.beta is not None


def test_map_return_summary_ok_and_suppressed() -> None:
    ok = svc._map_return_summary(
        ReturnSummary(
            observations_used=200,
            mean_daily_return=0.001,
            stdev_daily_return=0.02,
            cumulative_return=0.5,
            min_daily_return=-0.08,
            max_daily_return=0.09,
        )
    )
    assert ok.status == "ok"
    assert ok.cumulative_return == 0.5
    assert ok.observations_used == 200

    short = svc._map_return_summary(InsufficientObservations("return_summary", 60, 40))
    assert short.status == "insufficient_observations"
    assert (short.required, short.observations_used) == (60, 40)
    assert short.mean_daily_return is None


def test_map_var_es_carries_confidence_on_both_branches() -> None:
    ok = svc._map_var_es(
        HistoricalVarEsResult(
            confidence=0.95,
            var=0.04,
            expected_shortfall=0.06,
            threshold_return=-0.04,
            tail_observations=10,
            observations_used=200,
        ),
        confidence=0.95,
    )
    assert ok.status == "ok"
    assert ok.confidence == 0.95
    assert ok.method == "historical_lower_quantile"
    assert ok.horizon_days == 1

    short = svc._map_var_es(InsufficientObservations("historical_var_es", 126, 90), confidence=0.99)
    assert short.status == "insufficient_observations"
    assert short.confidence == 0.99
    assert short.var is None


def test_map_drawdown_translates_timestamps_to_dates() -> None:
    result = DrawdownResult(
        drawdown_series=pd.Series([0.0, -0.1], index=pd.to_datetime(["2024-01-02", "2024-01-03"])),
        max_drawdown=-0.1,
        peak_date=pd.Timestamp("2024-01-02"),
        trough_date=pd.Timestamp("2024-01-03"),
        recovery_date=None,
        recovered=False,
        observations_used=200,
    )
    metric = svc._map_drawdown(result)
    assert metric.status == "ok"
    assert metric.peak_date == datetime.date(2024, 1, 2)
    assert metric.trough_date == datetime.date(2024, 1, 3)
    assert metric.recovery_date is None
    assert metric.recovered is False


def test_map_sharpe_all_three_result_variants() -> None:
    ok = svc._map_sharpe(
        SharpeResult(
            sharpe_ratio=1.2,
            mean_daily_excess_return=0.001,
            daily_excess_volatility=0.02,
            observations_used=200,
            trading_days_per_year=252,
            risk_free_basis="daily_series",
        )
    )
    assert ok.status == "ok"
    assert ok.sharpe_ratio == 1.2
    assert ok.risk_free_basis == "daily_series"

    short = svc._map_sharpe(InsufficientObservations("sharpe_ratio", 126, 90))
    assert short.status == "insufficient_observations"
    assert short.required == 126
    assert short.sharpe_ratio is None

    undefined = svc._map_sharpe(UndefinedResult("sharpe_ratio", "zero excess-return variance", 130))
    assert undefined.status == "undefined"
    assert undefined.reason == "zero excess-return variance"


def test_map_beta_all_three_result_variants() -> None:
    ok = svc._map_beta(
        BetaResult(
            beta=1.5,
            alpha_daily=0.0001,
            r_squared=0.4,
            observations_used=200,
            aligned_start=pd.Timestamp("2024-01-02"),
            aligned_end=pd.Timestamp("2024-06-01"),
        )
    )
    assert ok.status == "ok"
    assert ok.beta == 1.5
    assert ok.aligned_start == datetime.date(2024, 1, 2)

    short = svc._map_beta(InsufficientObservations("capm_beta", 126, 90))
    assert short.status == "insufficient_observations"

    undefined = svc._map_beta(
        UndefinedResult("capm_beta", "benchmark excess return has zero variance", 130)
    )
    assert undefined.status == "undefined"
    assert undefined.reason == "benchmark excess return has zero variance"


def test_build_assumptions_when_rf_is_available() -> None:
    metrics: dict[str, svc.MetricBase] = {
        "return_summary": svc._map_return_summary(
            ReturnSummary(
                observations_used=200,
                mean_daily_return=0.0,
                stdev_daily_return=0.0,
                cumulative_return=0.0,
                min_daily_return=0.0,
                max_daily_return=0.0,
            )
        ),
    }
    assumptions = svc._build_assumptions(
        source="tiingo", as_of=datetime.date(2026, 9, 3), rf_available=True, metrics=metrics
    )
    assert assumptions.rf is None
    assert assumptions.rf_source == "kenneth_french_daily"
    assert assumptions.rf_basis == "daily_series"
    assert assumptions.benchmark == "SPY"
    assert assumptions.confidence_levels == [0.95, 0.99]
    assert assumptions.min_observations["var_es"] == 126
    assert assumptions.suppressed == []


def test_build_assumptions_lists_every_non_ok_metric_when_rf_is_missing() -> None:
    metrics: dict[str, svc.MetricBase] = {
        "sharpe": svc._compute_sharpe(
            pd.Series([0.01] * 130, index=pd.bdate_range("2023-01-02", periods=130)), None
        ),
        "beta": svc._compute_beta(
            object(),  # type: ignore[arg-type]
            asset_returns=pd.Series([0.01] * 130, index=pd.bdate_range("2023-01-02", periods=130)),
            source="tiingo",
            start=None,
            end=None,
            rf=None,
        ),
    }
    assumptions = svc._build_assumptions(
        source="tiingo", as_of=datetime.date(2026, 9, 3), rf_available=False, metrics=metrics
    )
    assert assumptions.rf is None
    assert assumptions.rf_source == "not_ingested"
    assert assumptions.rf_basis is None
    suppressed = {s.metric: s for s in assumptions.suppressed}
    assert set(suppressed) == {"sharpe", "beta"}
    assert all(s.status == "unavailable" for s in suppressed.values())
