"""PostgreSQL-backed tests for the Phase 2B / 2B.1 analytics API.

Skipped unless ``QUANTSCOPE_TEST_DATABASE_URL`` is set (see conftest). Data is
synthetic - ``PriceBar`` / ``FactorReturn`` rows inserted straight into the
migrated schema. These tests exercise the *wiring* (provenance, date windows,
adjusted-close basis, partial-metric availability, serialization, the RF /
SPY failure ladder); the statistical correctness of each metric is covered by
the Phase 2A engine unit tests and is not repeated here.

A single constant RF value is used throughout (``_RF_VALUE``): it keeps the
"excess return is exactly constant" edge cases (Sharpe/beta ``undefined``)
exact, while leaving every metric driven by a genuinely varying series (NVDA,
SPY, SHORTY) unaffected.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import exchange_calendars as xcals
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from quantscope.db.models import FactorReturn, PriceBar, Security

# Deterministic, non-degenerate daily-return patterns: mixed signs (a VaR tail),
# net drift, enough wobble for a real drawdown-and-recovery. NVDA and SPY use
# different patterns so beta is a genuine (not trivially perfect) regression.
_R_PATTERN = [0.010, -0.008, 0.006, -0.011, 0.009, 0.004, -0.013, 0.012]
_SPY_PATTERN = [0.005, -0.003, 0.002, 0.004, -0.006, 0.001, 0.003, -0.002]
_START = "2022-01-03"
_RF_VALUE = Decimal("0.000080")  # ~2%/yr, constant - see module docstring
_RF_SOURCE = "kenneth_french"


def _adj_path(n: int, *, base: float = 100.0, pattern: list[float] = _R_PATTERN) -> list[float]:
    path = [base]
    for i in range(1, n):
        path.append(round(path[-1] * (1.0 + pattern[(i - 1) % len(pattern)]), 6))
    return path


def _bdates(n: int) -> list[datetime.date]:
    """``n`` genuine, gap-free XNYS sessions from ``_START`` - unlike
    ``pd.bdate_range``, which includes US market holidays that are not real
    trading sessions. The analytics service now excludes any return spanning
    a missing session (QS-01), so fixtures must be calendar-continuous to
    keep their exact observation-count assertions meaningful."""
    cal = xcals.get_calendar("XNYS")
    first = cal.date_to_session(_START, direction="next")
    return [ts.date() for ts in cal.sessions_window(first, n)]


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
    adj_values: list[float] | None = None,
) -> list[datetime.date]:
    """Insert ``n`` daily bars. ``adj_close`` follows ``adj_values`` (default: the
    NVDA pattern); ``close`` is a flat sentinel by default so a test can prove
    analytics use ``adj_close``."""
    dates = _bdates(n)
    adj = adj_values if adj_values is not None else _adj_path(n)
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


def _insert_rf(
    session: Session,
    dates: list[datetime.date],
    *,
    value: Decimal = _RF_VALUE,
    source: str = _RF_SOURCE,
) -> None:
    for day in dates:
        session.add(
            FactorReturn(
                factor_name="rf", frequency="daily", trade_date=day, source=source, value=value
            )
        )
    session.flush()


@pytest.fixture
def universe(session: Session) -> dict[str, Any]:
    """NVDA (204 returns) + SPY (204 returns, a different pattern) + RF, all
    covering the same 205-day window; SHORTY and ONEBAR share the window's start
    but are too short for their own metrics regardless of RF/SPY availability."""
    nvda = _sec(session, "NVDA", "NVIDIA Corporation")
    spy = _sec(session, "SPY", "SPDR S&P 500 ETF Trust")
    shorty = _sec(session, "SHORTY", "Short History Inc.")
    onebar = _sec(session, "ONEBAR", "Single Bar Corp.")

    nvda_dates = _insert_bars(session, nvda, "tiingo", 205)
    _insert_bars(session, nvda, "stooq", 5)  # a second source, never merged
    _insert_bars(session, spy, "tiingo", 205, adj_values=_adj_path(205, pattern=_SPY_PATTERN))
    _insert_bars(session, shorty, "tiingo", 80)  # >= vol/dd gate (60), < sharpe/beta gate (126)
    _insert_bars(session, onebar, "tiingo", 1)  # no return series can be formed

    rf_dates = _bdates(205)  # covers every fixture's window
    _insert_rf(session, rf_dates)

    return {
        "nvda_dates": nvda_dates,
        "adj_path": _adj_path(205),
        "rf_dates": rf_dates,
    }


def _get(client: TestClient, ticker: str, **params: str) -> dict[str, Any]:
    resp = client.get(f"/securities/{ticker}/analytics", params=params)
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


# --------------------------------------------------------------------------- #
# QS-01: a missing interior XNYS session is never bridged into one return
# --------------------------------------------------------------------------- #
def test_missing_interior_session_excludes_one_return_not_bridges_it(
    api_client: TestClient, session: Session
) -> None:
    """130 genuine, gap-free XNYS sessions, with the bar for one interior
    session (index 64) never persisted at all - a real vendor/ingestion gap,
    not a malformed row. 129 bars remain; of the 128 adjacent pairs, exactly
    the one spanning the gap (index 63 -> 65) must be excluded from the
    return series - never computed as a single, artificially large "daily"
    return - leaving 127 usable returns.
    """
    sec = _sec(session, "GAPPY", "Gappy Corp.")
    full_dates = _bdates(130)
    adj = _adj_path(130)
    gap_pos = 64
    kept_dates = full_dates[:gap_pos] + full_dates[gap_pos + 1 :]
    kept_adj = adj[:gap_pos] + adj[gap_pos + 1 :]
    for day, value in zip(kept_dates, kept_adj, strict=True):
        session.add(
            PriceBar(
                security_id=sec,
                trade_date=day,
                source="tiingo",
                close=Decimal("100.000000"),
                adj_close=Decimal(str(value)),
            )
        )
    session.flush()
    _insert_rf(session, full_dates)

    body = _get(api_client, "GAPPY")
    assert body["price_observations"] == 129
    # 129 bars -> 128 adjacent pairs -> 1 excluded (spans the missing session) -> 127
    assert body["return_observations"] == 127
    # The excluded adjacency's "return" (adj[65]/adj[63] - 1, spanning two real
    # trading days at once) must never appear as a max/min daily return - both
    # remain within the hand-built pattern's true per-day range.
    pattern_extremes = (min(_R_PATTERN), max(_R_PATTERN))
    rs = body["return_summary"]
    tol = 1e-5  # rounding noise from _adj_path's round(..., 6)
    assert pattern_extremes[0] - tol <= rs["min_daily_return"] <= pattern_extremes[1] + tol
    assert pattern_extremes[0] - tol <= rs["max_daily_return"] <= pattern_extremes[1] + tol


def test_exactly_two_bars_spanning_a_gap_is_insufficient_not_a_crash(
    api_client: TestClient, session: Session
) -> None:
    """Pathological edge case: exactly 2 price bars, and the one possible
    adjacency between them spans a missing XNYS session. The gap-filtered
    return series is therefore *empty* even though 2 bars exist - this must
    report every metric as insufficient (0 observations), not raise (the
    quant engine's own validation treats a literally empty series as a
    structural error, reserved for a genuine caller bug, not a thin one)."""
    sec = _sec(session, "TWOGAP", "Two Bar Gap Co.")
    full_dates = _bdates(3)  # three consecutive sessions
    # Keep only the first and third - the middle (real) session is missing,
    # so the only adjacency between the two kept bars spans a gap.
    for day, value in zip([full_dates[0], full_dates[2]], [100.0, 101.0], strict=True):
        session.add(
            PriceBar(
                security_id=sec,
                trade_date=day,
                source="tiingo",
                close=Decimal("100.000000"),
                adj_close=Decimal(str(value)),
            )
        )
    session.flush()
    _insert_rf(session, full_dates)

    body = _get(api_client, "TWOGAP")
    assert body["price_observations"] == 2
    assert body["return_observations"] == 0
    for name in (
        "return_summary",
        "volatility",
        "drawdown",
        "var_es_95",
        "var_es_99",
        "sharpe",
        "beta",
    ):
        assert body[name]["status"] == "insufficient_observations", name
        assert body[name]["observations_used"] == 0


def test_fully_continuous_history_has_no_excluded_adjacency(
    api_client: TestClient, universe: dict[str, Any]
) -> None:
    # Regression guard: a genuinely gap-free XNYS window (the shared fixture)
    # loses nothing to the new adjacency check - 205 bars -> 204 returns,
    # exactly as before this fix.
    body = _get(api_client, "NVDA")
    assert body["price_observations"] == 205
    assert body["return_observations"] == 204


# --------------------------------------------------------------------------- #
# Core metrics + happy-path Sharpe / beta
# --------------------------------------------------------------------------- #
def test_full_history_all_metrics_ok(api_client: TestClient, universe: dict[str, Any]) -> None:
    body = _get(api_client, "NVDA")
    dates: list[datetime.date] = universe["nvda_dates"]
    adj: list[float] = universe["adj_path"]

    assert body["source"] == "tiingo"
    assert body["adjustment_basis"] == "adjusted_close"
    assert body["price_observations"] == 205
    assert body["return_observations"] == 204
    assert body["analytics_start"] == dates[1].isoformat()
    assert body["analytics_end"] == dates[-1].isoformat()

    for name in (
        "return_summary",
        "volatility",
        "drawdown",
        "var_es_95",
        "var_es_99",
        "sharpe",
        "beta",
    ):
        assert body[name]["status"] == "ok", (name, body[name])

    assert body["return_summary"]["cumulative_return"] == pytest.approx(
        adj[-1] / adj[0] - 1.0, rel=1e-6
    )
    assert body["volatility"]["annualised_volatility"] > 0.0
    assert body["drawdown"]["max_drawdown"] <= 0.0

    assert body["sharpe"]["sharpe_ratio"] is not None
    assert body["sharpe"]["observations_used"] == 204
    assert body["sharpe"]["risk_free_basis"] == "daily_series"

    assert body["beta"]["beta"] is not None
    assert body["beta"]["alpha_daily"] is not None
    assert body["beta"]["observations_used"] == 204
    assert body["beta"]["aligned_start"] == dates[1].isoformat()
    assert body["beta"]["aligned_end"] == dates[-1].isoformat()

    assert body["assumptions"]["suppressed"] == []


def test_ticker_is_normalised(api_client: TestClient, universe: dict[str, Any]) -> None:
    body = _get(api_client, "nvda")
    assert body["ticker"] == "NVDA"


def test_unknown_ticker_is_404(api_client: TestClient, universe: dict[str, Any]) -> None:
    resp = api_client.get("/securities/ZZZZ/analytics")
    assert resp.status_code == 404


def test_thin_history_suppresses_var_es_sharpe_and_beta_not_volatility(
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

    # RF and SPY are both present, but SHORTY's own history is too short for
    # either gate - this is the "insufficient overlap" path, not "unavailable".
    assert body["sharpe"]["status"] == "insufficient_observations"
    assert body["sharpe"]["required"] == 126
    assert body["sharpe"]["observations_used"] == 79
    assert body["beta"]["status"] == "insufficient_observations"
    assert body["beta"]["required"] == 126
    assert body["beta"]["observations_used"] == 79

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
    assert body["sharpe"]["status"] == "insufficient_observations"
    assert body["sharpe"]["required"] == 126
    assert body["sharpe"]["observations_used"] == 0
    assert body["beta"]["status"] == "insufficient_observations"
    assert body["beta"]["required"] == 126
    assert body["beta"]["observations_used"] == 0


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
    # 80 < 126: sharpe/beta insufficient in this narrower window even though
    # RF/SPY cover it - not a provenance problem.
    assert body["sharpe"]["status"] == "insufficient_observations"
    assert body["beta"]["status"] == "insufficient_observations"


def test_start_after_end_is_422(api_client: TestClient, universe: dict[str, Any]) -> None:
    resp = api_client.get(
        "/securities/NVDA/analytics", params={"start": "2024-06-01", "end": "2024-01-01"}
    )
    assert resp.status_code == 422


def test_price_sources_are_never_merged(api_client: TestClient, universe: dict[str, Any]) -> None:
    # NVDA also has 5 bars under "stooq" (inserted by the `universe` fixture);
    # the default tiingo-sourced response must never merge them in.
    default = _get(api_client, "NVDA")
    assert default["source"] == "tiingo"
    assert default["price_observations"] == 205  # not 210


def test_stooq_source_is_rejected_for_analytics(
    api_client: TestClient, universe: dict[str, Any]
) -> None:
    # QS-06: Stooq's single, ambiguous Close has no documented adjustment rule
    # (ADR 0022) - it must never be presented as verified adjusted-close /
    # total-return analytics. Rejected at request validation, not silently
    # computed.
    resp = api_client.get("/securities/NVDA/analytics", params={"source": "stooq"})
    assert resp.status_code == 422


def test_configured_stooq_default_is_rejected_when_source_is_omitted(
    api_client: TestClient,
    universe: dict[str, Any],
    configured_stooq_provider: None,
) -> None:
    # RA-02: QS-06 rejected an *explicit* source=stooq, but a deployment
    # configured with QUANTSCOPE_PRICE_PROVIDER=stooq could previously reach
    # analytics simply by omitting `source` altogether, inheriting Stooq
    # through the settings fallback that FastAPI's query-parameter Literal
    # validation never sees. This must be rejected the same way.
    resp = api_client.get("/securities/NVDA/analytics")
    assert resp.status_code == 422
    assert "stooq" in resp.json()["detail"].lower()


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
    assert _types("AnalyticsAssumptions", "rf_basis") == {"string", "null"}
    assert schemas["AnalyticsResponse"]["properties"]["price_observations"]["type"] == "integer"


def test_assumptions_block_reports_kenneth_french_provenance(
    api_client: TestClient, universe: dict[str, Any]
) -> None:
    a = _get(api_client, "NVDA")["assumptions"]
    assert a["annualisation_factor"] == 252
    assert a["calendar"] == "XNYS"
    assert a["return_type"] == "total"
    assert a["adjustment_basis"] == "adjusted_close"
    assert a["rf"] is None  # it's a time series now, never a scalar
    assert a["rf_source"] == "kenneth_french_daily"
    assert a["rf_basis"] == "daily_series"
    assert a["benchmark"] == "SPY" and a["market_proxy"] == "SPY"
    assert a["var_horizon_days"] == 1 and a["var_scaling"] == "none"
    assert a["confidence_levels"] == [0.95, 0.99]
    assert a["min_observations"]["sharpe"] == 126
    assert a["min_observations"]["beta"] == 126
    assert a["min_observations"]["volatility"] == 60
    assert a["suppressed"] == []  # everything is ok for full-history NVDA


def test_phase_1e_endpoints_still_work(api_client: TestClient, universe: dict[str, Any]) -> None:
    assert api_client.get("/securities/NVDA").json()["ticker"] == "NVDA"
    prices = api_client.get("/securities/NVDA/prices", params={"source": "tiingo"}).json()
    assert prices["count"] == len(prices["results"]) and prices["results"]
    assert api_client.get("/securities", params={"q": "NV"}).status_code == 200


# --------------------------------------------------------------------------- #
# RF / SPY failure ladder (each test builds its own minimal, isolated fixture)
# --------------------------------------------------------------------------- #
def test_missing_rf_leaves_sharpe_and_beta_unavailable_but_others_ok(
    session: Session, api_client: TestClient
) -> None:
    nvda = _sec(session, "NVDA", "NVIDIA Corporation")
    spy = _sec(session, "SPY", "SPDR S&P 500 ETF Trust")
    _insert_bars(session, nvda, "tiingo", 205)
    _insert_bars(session, spy, "tiingo", 205, adj_values=_adj_path(205, pattern=_SPY_PATTERN))
    # deliberately no FactorReturn rows at all

    body = _get(api_client, "NVDA")
    for name in ("return_summary", "volatility", "drawdown", "var_es_95", "var_es_99"):
        assert body[name]["status"] == "ok", name
    assert body["sharpe"] == {
        "status": "unavailable",
        "observations_used": None,
        "required": None,
        "reason": "risk_free_series_not_ingested",
        "sharpe_ratio": None,
        "mean_daily_excess_return": None,
        "daily_excess_volatility": None,
        "trading_days_per_year": 252,
        "risk_free_basis": None,
    }
    assert body["beta"]["status"] == "unavailable"
    assert body["beta"]["reason"] == "risk_free_series_not_ingested"

    a = body["assumptions"]
    assert a["rf_source"] == "not_ingested"
    assert a["rf_basis"] is None
    suppressed = {s["metric"]: s for s in a["suppressed"]}
    assert suppressed["sharpe"]["reason"] == "risk_free_series_not_ingested"
    assert suppressed["beta"]["reason"] == "risk_free_series_not_ingested"


def test_missing_spy_security_leaves_beta_unavailable_but_sharpe_ok(
    session: Session, api_client: TestClient
) -> None:
    nvda = _sec(session, "NVDA", "NVIDIA Corporation")
    nvda_dates = _insert_bars(session, nvda, "tiingo", 205)
    _insert_rf(session, nvda_dates)
    # no SPY security row at all

    body = _get(api_client, "NVDA")
    assert body["sharpe"]["status"] == "ok"
    assert body["beta"]["status"] == "unavailable"
    assert body["beta"]["reason"] == "benchmark_security_not_found"
    for name in ("return_summary", "volatility", "drawdown", "var_es_95", "var_es_99"):
        assert body[name]["status"] == "ok", name


def test_spy_security_without_price_history_leaves_beta_unavailable(
    session: Session, api_client: TestClient
) -> None:
    nvda = _sec(session, "NVDA", "NVIDIA Corporation")
    nvda_dates = _insert_bars(session, nvda, "tiingo", 205)
    _insert_rf(session, nvda_dates)
    _sec(session, "SPY", "SPDR S&P 500 ETF Trust")  # seeded, but zero price_bar rows

    body = _get(api_client, "NVDA")
    assert body["sharpe"]["status"] == "ok"
    assert body["beta"]["status"] == "unavailable"
    assert body["beta"]["reason"] == "benchmark_price_history_unavailable"


def test_spy_gapped_to_zero_returns_leaves_beta_insufficient_not_unavailable(
    session: Session, api_client: TestClient
) -> None:
    """SPY-01: SPY has >= 2 persisted bars, but its one possible adjacency
    spans a missing XNYS session, leaving zero usable benchmark returns.
    SPY's price history is not missing, so `unavailable` would misrepresent
    this - beta must report `insufficient_observations` / `observations_used:
    0`, the same as a thin RF series (same MIN_OBS_BETA gate). NVDA's own
    history is fully continuous, so sharpe (unaffected by SPY) stays `ok`."""
    nvda = _sec(session, "NVDA", "NVIDIA Corporation")
    nvda_dates = _insert_bars(session, nvda, "tiingo", 205)
    _insert_rf(session, nvda_dates)

    spy = _sec(session, "SPY", "SPDR S&P 500 ETF Trust")
    full_dates = _bdates(3)  # three consecutive sessions
    # Keep only the first and third - the middle (real) session is missing,
    # so the only adjacency between the two kept SPY bars spans a gap.
    for day, value in zip([full_dates[0], full_dates[2]], [400.0, 401.0], strict=True):
        session.add(
            PriceBar(
                security_id=spy,
                trade_date=day,
                source="tiingo",
                close=Decimal("400.000000"),
                adj_close=Decimal(str(value)),
            )
        )
    session.flush()

    body = _get(api_client, "NVDA")
    assert body["sharpe"]["status"] == "ok"
    assert body["beta"]["status"] == "insufficient_observations"
    assert body["beta"]["observations_used"] == 0
    assert body["beta"]["required"] == 126
    assert body["beta"]["reason"] is None


def test_sharpe_undefined_for_zero_excess_variance(
    session: Session, api_client: TestClient
) -> None:
    flat = _sec(session, "FLATCO", "Flat Return Corp.")
    flat_dates = _insert_bars(session, flat, "tiingo", 205, adj_values=[100.0] * 205)
    _insert_rf(session, flat_dates)

    body = _get(api_client, "FLATCO")
    assert body["volatility"]["status"] == "ok"
    assert body["volatility"]["annualised_volatility"] == pytest.approx(0.0)
    assert body["sharpe"]["status"] == "undefined"
    assert body["sharpe"]["reason"] == "zero excess-return variance"
    assert body["sharpe"]["sharpe_ratio"] is None


def test_beta_r_squared_null_for_constant_asset_excess_return(
    session: Session, api_client: TestClient
) -> None:
    flat = _sec(session, "FLATCO", "Flat Return Corp.")
    spy = _sec(session, "SPY", "SPDR S&P 500 ETF Trust")
    flat_dates = _insert_bars(session, flat, "tiingo", 205, adj_values=[100.0] * 205)
    _insert_bars(session, spy, "tiingo", 205, adj_values=_adj_path(205, pattern=_SPY_PATTERN))
    _insert_rf(session, flat_dates)

    body = _get(api_client, "FLATCO")
    assert body["beta"]["status"] == "ok"
    assert body["beta"]["r_squared"] is None
    assert body["beta"]["beta"] == pytest.approx(0.0, abs=1e-9)
    assert body["beta"]["alpha_daily"] is not None


def test_beta_undefined_for_constant_benchmark_excess_return(
    session: Session, api_client: TestClient
) -> None:
    nvda = _sec(session, "NVDA", "NVIDIA Corporation")
    spy = _sec(session, "SPY", "SPDR S&P 500 ETF Trust")
    nvda_dates = _insert_bars(session, nvda, "tiingo", 205)
    _insert_bars(session, spy, "tiingo", 205, adj_values=[100.0] * 205)  # flat SPY
    _insert_rf(session, nvda_dates)

    body = _get(api_client, "NVDA")
    assert body["sharpe"]["status"] == "ok"  # unaffected by the flat benchmark
    assert body["beta"]["status"] == "undefined"
    assert body["beta"]["reason"] == "benchmark excess return has zero variance"
