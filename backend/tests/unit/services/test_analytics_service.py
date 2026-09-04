"""Focused unit tests for the analytics service helpers (no database).

These cover the *plumbing* only - series assembly from ORM rows, dataclass ->
schema mapping, the Phase 2B risk-free seam, and the assumptions block. The
statistical correctness of the metrics themselves is already covered by the
Phase 2A engine unit tests and is not re-tested here.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pandas as pd

from quantscope.db.models import PriceBar
from quantscope.quant import (
    DrawdownResult,
    HistoricalVarEsResult,
    InsufficientObservations,
    ReturnSummary,
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


def test_adjusted_close_series_uses_adj_close_not_raw_close() -> None:
    bars = [_bar("2024-01-02", "95.20", close="100.10"), _bar("2024-01-03", "96.00", close="101.0")]
    series = svc._adjusted_close_series(bars)

    assert isinstance(series.index, pd.DatetimeIndex)
    assert list(series) == [95.20, 96.00]  # adj_close, not close
    assert series.dtype == "float64"
    assert list(series.index) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]


def test_load_daily_risk_free_is_none_until_m2() -> None:
    assert svc._load_daily_risk_free(None, start=None, end=None) is None  # type: ignore[arg-type]


def test_sharpe_and_beta_are_unavailable_with_rf_reason() -> None:
    sharpe = svc._sharpe_unavailable()
    beta = svc._beta_unavailable()
    assert sharpe.status == "unavailable"
    assert sharpe.reason == "risk_free_series_not_ingested"
    assert sharpe.sharpe_ratio is None
    assert beta.status == "unavailable"
    assert beta.reason == "risk_free_series_not_ingested"
    assert beta.beta is None


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


def test_build_assumptions_lists_every_non_ok_metric() -> None:
    metrics = {
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
        "sharpe": svc._sharpe_unavailable(),
        "beta": svc._beta_unavailable(),
    }
    assumptions = svc._build_assumptions(
        source="tiingo", as_of=datetime.date(2026, 9, 3), metrics=metrics
    )
    assert assumptions.annualisation_factor == 252
    assert assumptions.rf is None
    assert assumptions.rf_source == "none_pending_fama_french_ingestion"
    assert assumptions.benchmark == "SPY"
    assert assumptions.confidence_levels == [0.95, 0.99]
    assert assumptions.min_observations["var_es"] == 126
    suppressed = {s.metric: s for s in assumptions.suppressed}
    assert set(suppressed) == {"sharpe", "beta"}
    assert all(s.status == "unavailable" for s in suppressed.values())
