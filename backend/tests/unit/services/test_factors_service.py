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

import pandas as pd
import pytest
from sqlalchemy.orm import Session

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


def test_load_daily_risk_free_none_when_nothing_persisted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "get_factor_series", lambda session, **kw: [])
    assert svc._load_daily_risk_free(_SESSION, start=None, end=None) is None


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


def test_load_ff3_factor_panel_omits_a_factor_with_no_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_factor("mkt_rf", "2024-01-02", "0.001"), _factor("smb", "2024-01-02", "0.0005")]
    monkeypatch.setattr(svc, "get_factor_panel", lambda session, **kw: rows)
    panel = svc._load_ff3_factor_panel(_SESSION, start=None, end=None)
    assert set(panel) == {"mkt_rf", "smb"}
    assert "hml" not in panel


# --------------------------------------------------------------------------- #
# SPY resolution
# --------------------------------------------------------------------------- #
def test_resolve_spy_returns_unavailable_when_benchmark_security_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(svc, "get_security_by_ticker", lambda session, ticker: None)
    returns, reason = svc._resolve_spy_returns(
        _SESSION,
        source="tiingo",
        start=None,
        end=None,
    )
    assert returns is None
    assert reason == "benchmark_security_not_found"


def test_resolve_spy_returns_unavailable_when_benchmark_has_thin_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = Security(id=99, ticker="SPY", name="SPY", exchange="XNAS")
    monkeypatch.setattr(svc, "get_security_by_ticker", lambda session, ticker: spy)
    monkeypatch.setattr(svc, "get_all_price_bars", lambda session, **kw: [_bar("2024-01-02", "10")])
    returns, reason = svc._resolve_spy_returns(
        _SESSION,
        source="tiingo",
        start=None,
        end=None,
    )
    assert returns is None
    assert reason == "benchmark_price_history_unavailable"


def test_resolve_spy_returns_ok_when_history_present(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = pd.bdate_range("2023-01-02", periods=5)
    spy = Security(id=99, ticker="SPY", name="SPY", exchange="XNAS")
    spy_bars = [_bar(str(d.date()), str(100.0 + i)) for i, d in enumerate(dates)]
    monkeypatch.setattr(svc, "get_security_by_ticker", lambda session, ticker: spy)
    monkeypatch.setattr(svc, "get_all_price_bars", lambda session, **kw: spy_bars)
    returns, reason = svc._resolve_spy_returns(
        _SESSION,
        source="tiingo",
        start=None,
        end=None,
    )
    assert reason is None
    assert returns is not None
    assert len(returns) == 4


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


def test_compute_ticker_factors_both_unavailable_when_rf_missing_and_never_queries_spy_or_factors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = pd.bdate_range("2023-01-02", periods=130)
    price_bars = [_bar(str(d.date()), str(100.0 + i * 0.1)) for i, d in enumerate(dates)]

    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("should not query SPY/factors when RF is absent")

    monkeypatch.setattr(svc, "get_all_price_bars", lambda session, **kw: price_bars)
    monkeypatch.setattr(svc, "get_factor_series", lambda session, **kw: [])
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
    dates = pd.bdate_range("2023-01-02", periods=130)
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
    dates = pd.bdate_range("2023-01-02", periods=260)
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
