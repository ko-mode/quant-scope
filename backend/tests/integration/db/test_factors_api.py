"""PostgreSQL-backed tests for the Phase 3B factors API
(``GET /securities/{ticker}/factors``).

Skipped unless ``QUANTSCOPE_TEST_DATABASE_URL`` is set (see conftest). Data is
synthetic - ``PriceBar`` / ``FactorReturn`` rows inserted straight into the
migrated schema. These tests exercise the *wiring* (provenance, date windows,
per-model independence, the unavailable/insufficient/undefined ladder,
serialization); the statistical correctness of each regression is covered by
the Phase 3B quant engine unit tests (``tests/unit/quant/test_factors.py``)
and is not repeated here.

Missing-input scenarios (RF, SPY, one factor) each build their own isolated,
minimal fixture rather than reusing ``universe`` - mirroring
``test_analytics_api.py``'s convention exactly.
"""

from __future__ import annotations

import datetime
import math
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from quantscope.db.models import FactorReturn, PriceBar, Security
from quantscope.quant.factors import newey_west_lags

# Deterministic, non-degenerate daily-return patterns - distinct for every
# series so no pair is ever exactly collinear.
_R_PATTERN = [0.010, -0.008, 0.006, -0.011, 0.009, 0.004, -0.013, 0.012]
_SPY_PATTERN = [0.005, -0.003, 0.002, 0.004, -0.006, 0.001, 0.003, -0.002]
_MKT_PATTERN = [0.0006, -0.0004, 0.0005, -0.0003, 0.0004]
_SMB_PATTERN = [0.0002, -0.0003, 0.0004, -0.0001, 0.0003]
_HML_PATTERN = [-0.0003, 0.0002, -0.0004, 0.0003, -0.0002]
_START = "2022-01-03"
_RF_VALUE = Decimal("0.000080")
_FACTOR_SOURCE = "kenneth_french"


def _adj_path(n: int, *, base: float = 100.0, pattern: list[float] = _R_PATTERN) -> list[float]:
    path = [base]
    for i in range(1, n):
        path.append(round(path[-1] * (1.0 + pattern[(i - 1) % len(pattern)]), 6))
    return path


def _bdates(n: int, start: str = _START) -> list[datetime.date]:
    return [ts.date() for ts in pd.bdate_range(start, periods=n)]


def _sec(session: Session, ticker: str, name: str) -> int:
    row = Security(ticker=ticker, name=name, exchange="XNAS", asset_type="common_stock")
    session.add(row)
    session.flush()
    return row.id


def _insert_bars(
    session: Session,
    security_id: int,
    source: str,
    n: int,
    *,
    adj_values: list[float] | None = None,
    start: str = _START,
) -> list[datetime.date]:
    dates = _bdates(n, start)
    adj = adj_values if adj_values is not None else _adj_path(n)
    for day, value in zip(dates, adj, strict=True):
        session.add(
            PriceBar(
                security_id=security_id,
                trade_date=day,
                source=source,
                close=Decimal("100.000000"),
                adj_close=Decimal(str(value)),
            )
        )
    session.flush()
    return dates


def _insert_factor(
    session: Session,
    factor_name: str,
    dates: list[datetime.date],
    values: list[float] | None = None,
    *,
    constant: Decimal | None = None,
    source: str = _FACTOR_SOURCE,
) -> None:
    for i, day in enumerate(dates):
        if constant is not None:
            value = constant
        else:
            assert values is not None
            value = Decimal(str(values[i % len(values)]))
        session.add(
            FactorReturn(
                factor_name=factor_name,
                frequency="daily",
                trade_date=day,
                source=source,
                value=value,
            )
        )
    session.flush()


def _insert_rf(session: Session, dates: list[datetime.date], *, value: Decimal = _RF_VALUE) -> None:
    _insert_factor(session, "rf", dates, constant=value)


def _insert_ff3_factors(session: Session, dates: list[datetime.date]) -> None:
    _insert_factor(session, "mkt_rf", dates, _MKT_PATTERN)
    _insert_factor(session, "smb", dates, _SMB_PATTERN)
    _insert_factor(session, "hml", dates, _HML_PATTERN)


@pytest.fixture
def universe(session: Session) -> dict[str, Any]:
    """NVDA (260 returns, clears both gates) + SPY (260 returns) + MIDHIST (200
    bars: clears CAPM's 126 gate but not FF3's 250) + ONEBAR, all sharing one
    260-day RF / Mkt-RF / SMB / HML window."""
    nvda = _sec(session, "NVDA", "NVIDIA Corporation")
    spy = _sec(session, "SPY", "SPDR S&P 500 ETF Trust")
    midhist = _sec(session, "MIDHIST", "Mid History Inc.")
    onebar = _sec(session, "ONEBAR", "Single Bar Corp.")

    nvda_dates = _insert_bars(session, nvda, "tiingo", 260)
    _insert_bars(session, spy, "tiingo", 260, adj_values=_adj_path(260, pattern=_SPY_PATTERN))
    _insert_bars(session, midhist, "tiingo", 200)
    _insert_bars(session, onebar, "tiingo", 1)

    factor_dates = _bdates(260)
    _insert_rf(session, factor_dates)
    _insert_ff3_factors(session, factor_dates)

    return {"nvda_dates": nvda_dates, "factor_dates": factor_dates}


def _get(client: TestClient, ticker: str, **params: str) -> dict[str, Any]:
    resp = client.get(f"/securities/{ticker}/factors", params=params)
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _walk_floats(node: Any) -> list[float]:
    """Every float leaf in a JSON-decoded body - used to assert no NaN/Infinity."""
    if isinstance(node, float):
        return [node]
    if isinstance(node, dict):
        return [f for v in node.values() for f in _walk_floats(v)]
    if isinstance(node, list):
        return [f for v in node for f in _walk_floats(v)]
    return []


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_full_history_capm_and_ff3_ok(api_client: TestClient, universe: dict[str, Any]) -> None:
    body = _get(api_client, "NVDA")
    dates: list[datetime.date] = universe["nvda_dates"]

    assert body["ticker"] == "NVDA"
    assert body["source"] == "tiingo"
    assert body["adjustment_basis"] == "adjusted_close"

    capm, ff3 = body["capm"], body["ff3"]
    assert capm["status"] == "ok", capm
    assert ff3["status"] == "ok", ff3

    assert [c["name"] for c in capm["coefficients"]] == ["alpha", "spy_excess"]
    assert [c["name"] for c in ff3["coefficients"]] == ["alpha", "mkt_rf", "smb", "hml"]

    assert capm["observations_used"] == 259
    assert capm["aligned_start"] == dates[1].isoformat()
    assert capm["aligned_end"] == dates[-1].isoformat()
    assert capm["hac_lags"] == newey_west_lags(259)
    assert ff3["hac_lags"] == newey_west_lags(259)

    for model in (capm, ff3):
        assert model["r_squared"] is not None
        for coef in model["coefficients"]:
            assert coef["estimate"] is not None
            # near-real (noisy-ish, not exactly collinear) data: every inference
            # field is present, none silently dropped to null.
            assert coef["std_error"] is not None
            assert coef["t_stat"] is not None
            assert coef["p_value"] is not None

    a = body["assumptions"]
    assert "different quantities" in a["capm_vs_ff3_note"]
    assert "SPY" in a["capm_vs_ff3_note"] and "Mkt-RF" in a["capm_vs_ff3_note"]
    assert "not annualized" in a["alpha_note"]
    assert a["factor_source"] == "kenneth_french"
    assert a["factor_frequency"] == "daily"
    assert a["rf_source"] == "kenneth_french_daily"
    assert a["min_observations"] == {"capm_regression": 126, "ff3_regression": 250}


def test_ticker_is_normalised(api_client: TestClient, universe: dict[str, Any]) -> None:
    assert _get(api_client, "nvda")["ticker"] == "NVDA"


def test_unknown_ticker_is_404(api_client: TestClient, universe: dict[str, Any]) -> None:
    assert api_client.get("/securities/ZZZZ/factors").status_code == 404


def test_start_after_end_is_422(api_client: TestClient, universe: dict[str, Any]) -> None:
    resp = api_client.get(
        "/securities/NVDA/factors", params={"start": "2024-06-01", "end": "2024-01-01"}
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# CAPM ok, FF3 insufficient (one model succeeds while the other doesn't)
# --------------------------------------------------------------------------- #
def test_capm_ok_ff3_insufficient_between_the_two_gates(
    api_client: TestClient, universe: dict[str, Any]
) -> None:
    body = _get(api_client, "MIDHIST")  # 200 bars -> 199 returns: clears 126, not 250
    assert body["capm"]["status"] == "ok"
    assert body["ff3"]["status"] == "insufficient_observations"
    assert body["ff3"]["required"] == 250
    assert body["ff3"]["observations_used"] == 199


# --------------------------------------------------------------------------- #
# Missing-input ladder (unavailable) - each an isolated minimal fixture
# --------------------------------------------------------------------------- #
def test_missing_price_history_both_unavailable(api_client: TestClient, session: Session) -> None:
    sec = _sec(session, "ONEONLY", "One Bar Co.")
    _insert_bars(session, sec, "tiingo", 1)
    body = _get(api_client, "ONEONLY")
    assert body["capm"]["status"] == "unavailable"
    assert body["capm"]["reason"] == "asset_price_history_unavailable"
    assert body["ff3"]["status"] == "unavailable"
    assert body["ff3"]["reason"] == "asset_price_history_unavailable"


def test_missing_rf_leaves_both_unavailable(api_client: TestClient, session: Session) -> None:
    sec = _sec(session, "NORF", "No RF Co.")
    dates = _insert_bars(session, sec, "tiingo", 130)
    spy = _sec(session, "SPY", "SPDR S&P 500 ETF Trust")
    _insert_bars(session, spy, "tiingo", 130, adj_values=_adj_path(130, pattern=_SPY_PATTERN))
    _insert_ff3_factors(session, dates)  # factors present, RF is not

    body = _get(api_client, "NORF")
    assert body["capm"]["status"] == "unavailable"
    assert body["capm"]["reason"] == "risk_free_series_not_ingested"
    assert body["ff3"]["status"] == "unavailable"
    assert body["ff3"]["reason"] == "risk_free_series_not_ingested"
    assert body["assumptions"]["rf_source"] == "not_ingested"


def test_missing_spy_leaves_capm_unavailable_ff3_unaffected(
    api_client: TestClient, session: Session
) -> None:
    sec = _sec(session, "NOSPY", "No SPY Co.")
    dates = _insert_bars(session, sec, "tiingo", 260)
    _insert_rf(session, dates)
    _insert_ff3_factors(session, dates)
    # deliberately no SPY security row at all

    body = _get(api_client, "NOSPY")
    assert body["capm"]["status"] == "unavailable"
    assert body["capm"]["reason"] == "benchmark_security_not_found"
    assert body["ff3"]["status"] == "ok"


def test_spy_without_price_history_leaves_capm_unavailable(
    api_client: TestClient, session: Session
) -> None:
    sec = _sec(session, "SPYNOHIST", "Spy No Hist Co.")
    dates = _insert_bars(session, sec, "tiingo", 260)
    _insert_rf(session, dates)
    _insert_ff3_factors(session, dates)
    _sec(session, "SPY", "SPDR S&P 500 ETF Trust")  # security exists, zero price bars

    body = _get(api_client, "SPYNOHIST")
    assert body["capm"]["status"] == "unavailable"
    assert body["capm"]["reason"] == "benchmark_price_history_unavailable"
    assert body["ff3"]["status"] == "ok"


def test_missing_one_factor_leaves_ff3_unavailable_capm_unaffected(
    api_client: TestClient, session: Session
) -> None:
    sec = _sec(session, "NOHML", "No HML Co.")
    dates = _insert_bars(session, sec, "tiingo", 260)
    spy = _sec(session, "SPY", "SPDR S&P 500 ETF Trust")
    _insert_bars(session, spy, "tiingo", 260, adj_values=_adj_path(260, pattern=_SPY_PATTERN))
    _insert_rf(session, dates)
    _insert_factor(session, "mkt_rf", dates, _MKT_PATTERN)
    _insert_factor(session, "smb", dates, _SMB_PATTERN)
    # hml never ingested for this source

    body = _get(api_client, "NOHML")
    assert body["capm"]["status"] == "ok"
    assert body["ff3"]["status"] == "unavailable"
    assert body["ff3"]["reason"] == "factor_not_ingested:hml"


# --------------------------------------------------------------------------- #
# Undefined (sufficient data, non-estimable regression) - never "unavailable"
# --------------------------------------------------------------------------- #
def test_zero_variance_factor_is_undefined_not_unavailable(
    api_client: TestClient, session: Session
) -> None:
    sec = _sec(session, "CONSTSMB", "Const SMB Co.")
    dates = _insert_bars(session, sec, "tiingo", 260)
    spy = _sec(session, "SPY", "SPDR S&P 500 ETF Trust")
    _insert_bars(session, spy, "tiingo", 260, adj_values=_adj_path(260, pattern=_SPY_PATTERN))
    _insert_rf(session, dates)
    _insert_factor(session, "mkt_rf", dates, _MKT_PATTERN)
    _insert_factor(session, "smb", dates, constant=Decimal("0.000000"))
    _insert_factor(session, "hml", dates, _HML_PATTERN)

    body = _get(api_client, "CONSTSMB")
    assert body["capm"]["status"] == "ok"
    assert body["ff3"]["status"] == "undefined"
    assert body["ff3"]["reason"] == "regressor 'smb' has zero variance"
    assert body["ff3"]["coefficients"] is None


# --------------------------------------------------------------------------- #
# Date-range windowing
# --------------------------------------------------------------------------- #
def test_date_range_propagates_requested_and_aligned_dates(
    api_client: TestClient, universe: dict[str, Any]
) -> None:
    dates: list[datetime.date] = universe["nvda_dates"]
    start, end = dates[10], dates[259]
    body = _get(api_client, "NVDA", start=start.isoformat(), end=end.isoformat())

    assert body["requested_start"] == start.isoformat()
    assert body["requested_end"] == end.isoformat()
    assert body["capm"]["status"] == "ok"
    assert body["capm"]["aligned_start"] == dates[11].isoformat()
    assert body["capm"]["aligned_end"] == dates[259].isoformat()


def test_price_sources_are_never_merged_factor_source_is_independent(
    api_client: TestClient, universe: dict[str, Any]
) -> None:
    # Adding a second, shorter price source for NVDA must not disturb the
    # kenneth_french factor lookup, which never depends on the price `source`.
    default = _get(api_client, "NVDA")
    assert default["capm"]["status"] == "ok"
    assert default["ff3"]["status"] == "ok"


# --------------------------------------------------------------------------- #
# JSON safety
# --------------------------------------------------------------------------- #
def test_no_nan_or_infinity_in_response(api_client: TestClient, universe: dict[str, Any]) -> None:
    body = _get(api_client, "NVDA")
    for value in _walk_floats(body):
        assert math.isfinite(value), value


def test_openapi_describes_factor_fields_as_numbers_not_strings(api_client: TestClient) -> None:
    schemas = api_client.get("/openapi.json").json()["components"]["schemas"]

    def _types(model: str, field: str) -> set[str]:
        prop = schemas[model]["properties"][field]
        return {v.get("type") for v in prop.get("anyOf", [prop])}

    assert _types("RegressionCoefficientSchema", "std_error") == {"number", "null"}
    assert _types("RegressionCoefficientSchema", "t_stat") == {"number", "null"}
    assert _types("RegressionCoefficientSchema", "p_value") == {"number", "null"}
    assert _types("FactorModelResult", "r_squared") == {"number", "null"}
    assert _types("FactorModelResult", "aligned_start") == {"string", "null"}
    assert schemas["RegressionCoefficientSchema"]["properties"]["estimate"]["type"] == "number"
