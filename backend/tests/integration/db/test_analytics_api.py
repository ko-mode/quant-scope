"""PostgreSQL-backed tests for the Phase 2B analytics API.

Skipped unless ``QUANTSCOPE_TEST_DATABASE_URL`` is set (see conftest). Data is
synthetic - ``PriceBar`` rows inserted straight into the migrated schema. These
tests exercise the *wiring* (provenance, date windows, adjusted-close basis,
partial-metric availability, serialization); the statistical correctness of each
metric is covered by the Phase 2A engine unit tests and is not repeated here.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from quantscope.db.models import PriceBar, Security

# A deterministic, non-degenerate daily-return pattern: mixed signs (a VaR tail),
# net drift up, and enough wobble for a real drawdown-and-recovery.
_R_PATTERN = [0.010, -0.008, 0.006, -0.011, 0.009, 0.004, -0.013, 0.012]
_START = "2022-01-03"


def _adj_path(n: int, base: float = 100.0) -> list[float]:
    path = [base]
    for i in range(1, n):
        path.append(round(path[-1] * (1.0 + _R_PATTERN[(i - 1) % len(_R_PATTERN)]), 6))
    return path


def _bdates(n: int) -> list[datetime.date]:
    return [ts.date() for ts in pd.bdate_range(_START, periods=n)]


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
    raw_close: Decimal | None = None,
) -> list[datetime.date]:
    """Insert ``n`` daily bars. ``adj_close`` follows ``_adj_path``; ``close`` is a
    flat sentinel by default so a test can prove analytics use ``adj_close``."""
    dates = _bdates(n)
    adj = _adj_path(n)
    for day, value in zip(dates, adj, strict=True):
        session.add(
            PriceBar(
                security_id=security_id,
                trade_date=day,
                source=source,
                close=raw_close if raw_close is not None else Decimal("100.000000"),
                adj_close=Decimal(str(value)),
            )
        )
    session.flush()
    return dates


@pytest.fixture
def universe(session: Session) -> dict[str, Any]:
    nvda = _sec(session, "NVDA", "NVIDIA Corporation")
    shorty = _sec(session, "SHORTY", "Short History Inc.")
    onebar = _sec(session, "ONEBAR", "Single Bar Corp.")

    nvda_dates = _insert_bars(session, nvda, "tiingo", 205)
    _insert_bars(session, nvda, "stooq", 5)  # a second source, never merged
    _insert_bars(session, shorty, "tiingo", 80)  # >= vol/dd gate (60), < VaR gate (126)
    _insert_bars(session, onebar, "tiingo", 1)  # no return series can be formed

    return {
        "nvda_dates": nvda_dates,
        "adj_path": _adj_path(205),
    }


def _get(client: TestClient, ticker: str, **params: str) -> dict[str, Any]:
    resp = client.get(f"/securities/{ticker}/analytics", params=params)
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


# --------------------------------------------------------------------------- #
def test_full_history_core_metrics_ok_sharpe_and_beta_unavailable(
    api_client: TestClient, universe: dict[str, Any]
) -> None:
    body = _get(api_client, "NVDA")
    dates: list[datetime.date] = universe["nvda_dates"]
    adj: list[float] = universe["adj_path"]

    assert body["source"] == "tiingo"
    assert body["adjustment_basis"] == "adjusted_close"
    assert body["price_observations"] == 205
    assert body["return_observations"] == 204
    assert body["analytics_start"] == dates[1].isoformat()
    assert body["analytics_end"] == dates[-1].isoformat()

    for name in ("return_summary", "volatility", "drawdown", "var_es_95", "var_es_99"):
        assert body[name]["status"] == "ok", (name, body[name])

    assert body["return_summary"]["cumulative_return"] == pytest.approx(
        adj[-1] / adj[0] - 1.0, rel=1e-6
    )
    assert body["volatility"]["annualised_volatility"] > 0.0
    assert body["volatility"]["trading_days_per_year"] == 252
    assert body["drawdown"]["max_drawdown"] <= 0.0
    assert body["drawdown"]["observations_used"] == 204

    for metric in ("sharpe", "beta"):
        assert body[metric]["status"] == "unavailable"
        assert body[metric]["reason"] == "risk_free_series_not_ingested"
    assert body["sharpe"]["sharpe_ratio"] is None
    assert body["beta"]["beta"] is None


def test_ticker_is_normalised(api_client: TestClient, universe: dict[str, Any]) -> None:
    body = _get(api_client, "nvda")
    assert body["ticker"] == "NVDA"


def test_unknown_ticker_is_404(api_client: TestClient, universe: dict[str, Any]) -> None:
    resp = api_client.get("/securities/ZZZZ/analytics")
    assert resp.status_code == 404


def test_thin_history_suppresses_var_es_not_volatility(
    api_client: TestClient, universe: dict[str, Any]
) -> None:
    body = _get(api_client, "SHORTY")  # 80 bars -> 79 returns
    assert body["return_observations"] == 79
    for name in ("return_summary", "volatility", "drawdown"):
        assert body[name]["status"] == "ok", name

    for name, conf in (("var_es_95", 0.95), ("var_es_99", 0.99)):
        block = body[name]
        assert block["status"] == "insufficient_observations"
        assert block["required"] == 126
        assert block["observations_used"] == 79
        assert block["confidence"] == conf
        assert block["var"] is None

    suppressed = {s["metric"] for s in body["assumptions"]["suppressed"]}
    assert {"var_es_95", "var_es_99", "sharpe", "beta"} <= suppressed


def test_single_bar_everything_insufficient(
    api_client: TestClient, universe: dict[str, Any]
) -> None:
    body = _get(api_client, "ONEBAR")
    assert body["price_observations"] == 1
    assert body["return_observations"] == 0
    assert body["analytics_start"] is None
    assert body["analytics_end"] is None
    assert body["assumptions"]["as_of"] is None

    for name in ("return_summary", "volatility", "drawdown", "var_es_95", "var_es_99"):
        assert body[name]["status"] == "insufficient_observations", name
        assert body[name]["observations_used"] == 0
    assert body["sharpe"]["status"] == "unavailable"
    assert body["beta"]["status"] == "unavailable"


def test_date_range_filters_the_window(api_client: TestClient, universe: dict[str, Any]) -> None:
    dates: list[datetime.date] = universe["nvda_dates"]
    start, end = dates[40], dates[120]
    body = _get(api_client, "NVDA", start=start.isoformat(), end=end.isoformat())

    assert body["requested_start"] == start.isoformat()
    assert body["requested_end"] == end.isoformat()
    assert body["price_observations"] == 81  # inclusive: indices 40..120
    assert body["return_observations"] == 80
    assert body["analytics_start"] == dates[41].isoformat()
    assert body["analytics_end"] == dates[120].isoformat()


def test_start_after_end_is_422(api_client: TestClient, universe: dict[str, Any]) -> None:
    resp = api_client.get(
        "/securities/NVDA/analytics", params={"start": "2024-06-01", "end": "2024-01-01"}
    )
    assert resp.status_code == 422


def test_price_sources_are_never_merged(api_client: TestClient, universe: dict[str, Any]) -> None:
    stooq = _get(api_client, "NVDA", source="stooq")
    assert stooq["source"] == "stooq"
    assert stooq["price_observations"] == 5  # not 205, not 210
    assert stooq["return_observations"] == 4

    default = _get(api_client, "NVDA")
    assert default["source"] == "tiingo"
    assert default["price_observations"] == 205


def test_analytics_use_adjusted_close_not_raw_close(
    api_client: TestClient, universe: dict[str, Any]
) -> None:
    # In the fixture raw `close` is a flat 100.0 for every bar; if analytics read
    # `close` the cumulative return would be exactly 0.
    body = _get(api_client, "NVDA")
    cumulative = body["return_summary"]["cumulative_return"]
    assert cumulative != pytest.approx(0.0, abs=1e-9)
    adj: list[float] = universe["adj_path"]
    assert cumulative == pytest.approx(adj[-1] / adj[0] - 1.0, rel=1e-6)


def test_var_es_95_and_99_present_and_ordered(
    api_client: TestClient, universe: dict[str, Any]
) -> None:
    body = _get(api_client, "NVDA")
    v95, v99 = body["var_es_95"], body["var_es_99"]
    assert v95["confidence"] == 0.95 and v99["confidence"] == 0.99
    assert v95["method"] == "historical_lower_quantile"
    assert v95["horizon_days"] == 1 and v99["horizon_days"] == 1
    # a deeper tail is at least as severe a loss
    assert v99["var"] >= v95["var"]
    assert v99["expected_shortfall"] >= v95["expected_shortfall"]


def test_openapi_describes_metric_fields_as_numbers_not_strings(
    api_client: TestClient,
) -> None:
    schemas = api_client.get("/openapi.json").json()["components"]["schemas"]

    def _types(model: str, field: str) -> set[str]:
        prop = schemas[model]["properties"][field]
        return {v.get("type") for v in prop.get("anyOf", [prop])}

    assert _types("VolatilityMetric", "annualised_volatility") == {"number", "null"}
    assert _types("SharpeMetric", "sharpe_ratio") == {"number", "null"}
    assert _types("BetaMetric", "r_squared") == {"number", "null"}
    assert _types("VarEsMetric", "var") == {"number", "null"}
    assert _types("DrawdownMetric", "peak_date") == {"string", "null"}
    assert schemas["AnalyticsResponse"]["properties"]["price_observations"]["type"] == "integer"


def test_assumptions_block_contract(api_client: TestClient, universe: dict[str, Any]) -> None:
    a = _get(api_client, "NVDA")["assumptions"]
    assert a["annualisation_factor"] == 252
    assert a["calendar"] == "XNYS"
    assert a["return_type"] == "total"
    assert a["adjustment_basis"] == "adjusted_close"
    assert a["rf"] is None
    assert isinstance(a["rf_source"], str) and a["rf_source"]
    assert a["benchmark"] == "SPY" and a["market_proxy"] == "SPY"
    assert a["var_horizon_days"] == 1 and a["var_scaling"] == "none"
    assert a["confidence_levels"] == [0.95, 0.99]
    assert a["min_observations"]["sharpe"] == 126
    assert a["min_observations"]["beta"] == 126
    assert a["min_observations"]["volatility"] == 60

    by_metric = {s["metric"]: s for s in a["suppressed"]}
    assert by_metric["sharpe"]["status"] == "unavailable"
    assert by_metric["sharpe"]["reason"] == "risk_free_series_not_ingested"
    assert by_metric["beta"]["status"] == "unavailable"


def test_phase_1e_endpoints_still_work(api_client: TestClient, universe: dict[str, Any]) -> None:
    assert api_client.get("/securities/NVDA").json()["ticker"] == "NVDA"
    prices = api_client.get("/securities/NVDA/prices", params={"source": "tiingo"}).json()
    assert prices["count"] == len(prices["results"]) and prices["results"]
    assert api_client.get("/securities", params={"q": "NV"}).status_code == 200
