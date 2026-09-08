"""PostgreSQL-backed tests for the Phase 3A comparison API (``GET /compare``).

Skipped unless ``QUANTSCOPE_TEST_DATABASE_URL`` is set (see conftest). Data is
synthetic - ``PriceBar`` rows inserted straight into the migrated schema. These
tests exercise the *wiring* (alignment, provenance, status transitions,
serialization); the statistical correctness of the panel/correlation itself is
covered by the Phase 3A quant engine unit tests and is not repeated here.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from typing import Any

import exchange_calendars as xcals
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from quantscope.db.models import PriceBar, Security

_A_PATTERN = [0.010, -0.008, 0.006, -0.011, 0.009, 0.004, -0.013, 0.012]
_B_PATTERN = [0.005, -0.003, 0.002, 0.004, -0.006, 0.001, 0.003, -0.002]
_START = "2022-01-03"


def _adj_path(n: int, *, base: float = 100.0, pattern: list[float] = _A_PATTERN) -> list[float]:
    path = [base]
    for i in range(1, n):
        path.append(round(path[-1] * (1.0 + pattern[(i - 1) % len(pattern)]), 6))
    return path


def _bdates(n: int) -> list[datetime.date]:
    """``n`` genuine, gap-free XNYS sessions from ``_START`` - unlike
    ``pd.bdate_range``, which includes US market holidays that are not real
    trading sessions. The comparison service now excludes any return spanning
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
    adj_values: list[float] | None = None,
) -> list[datetime.date]:
    dates = _bdates(n)
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


@pytest.fixture
def universe(session: Session) -> dict[str, Any]:
    aapl = _sec(session, "AAPL", "Apple Inc.")
    msft = _sec(session, "MSFT", "Microsoft Corporation")
    nvda = _sec(session, "NVDA", "NVIDIA Corporation")
    shorty = _sec(session, "SHORTY", "Short History Inc.")
    _sec(session, "NOHIST", "No History Corp.")  # security exists, zero price_bar rows
    flat = _sec(session, "FLATCO", "Flat Return Corp.")

    aapl_dates = _insert_bars(
        session, aapl, "tiingo", 100, adj_values=_adj_path(100, pattern=_A_PATTERN)
    )
    _insert_bars(session, aapl, "stooq", 5, adj_values=_adj_path(5, pattern=_A_PATTERN))
    _insert_bars(session, msft, "tiingo", 100, adj_values=_adj_path(100, pattern=_B_PATTERN))
    _insert_bars(
        session,
        nvda,
        "tiingo",
        100,
        adj_values=_adj_path(100, base=200.0, pattern=_B_PATTERN[::-1]),
    )
    _insert_bars(session, shorty, "tiingo", 10)
    _insert_bars(session, flat, "tiingo", 65, adj_values=[100.0] * 65)

    return {"aapl_dates": aapl_dates}


def _get(client: TestClient, **params: str) -> dict[str, Any]:
    resp = client.get("/compare", params=params)
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


# --------------------------------------------------------------------------- #
# QS-01: a per-ticker session gap narrows the aligned panel for that ticker
# only - it is never bridged into a fabricated multi-day return for either
# ticker, and the other ticker's own (gap-free) calendar is unaffected.
# --------------------------------------------------------------------------- #
def test_one_tickers_session_gap_narrows_the_aligned_panel_without_bridging(
    api_client: TestClient, session: Session
) -> None:
    aapl = _sec(session, "GAPA", "Gap A Corp.")
    gapb = _sec(session, "GAPB", "Gap B Corp.")
    full_dates = _bdates(70)
    gap_pos = 30  # interior session never persisted for GAPB only

    for day, value in zip(full_dates, _adj_path(70, pattern=_A_PATTERN), strict=True):
        session.add(
            PriceBar(
                security_id=aapl,
                trade_date=day,
                source="tiingo",
                close=Decimal("999"),
                adj_close=Decimal(str(value)),
            )
        )
    b_dates = full_dates[:gap_pos] + full_dates[gap_pos + 1 :]
    b_values = _adj_path(70, pattern=_B_PATTERN)
    b_values = b_values[:gap_pos] + b_values[gap_pos + 1 :]
    for day, value in zip(b_dates, b_values, strict=True):
        session.add(
            PriceBar(
                security_id=gapb,
                trade_date=day,
                source="tiingo",
                close=Decimal("999"),
                adj_close=Decimal(str(value)),
            )
        )
    session.flush()

    body = _get(api_client, tickers="GAPA,GAPB")
    assert body["status"] == "ok"
    # GAPA: 70 bars, no gap -> 69 valid returns (dates[1..69]).
    # GAPB: 69 bars (dates[30] missing) -> the dates[29]->dates[31] adjacency
    # is excluded -> 67 valid returns (dates[1..29] + dates[32..69]).
    # Aligned panel = intersection = GAPB's 67 dates (a strict subset of
    # GAPA's 69) - dates[30] and dates[31] are both absent from the panel,
    # even though GAPA itself has a perfectly valid return on dates[31].
    assert body["observations_used"] == 67
    assert body["aligned_start"] == full_dates[1].isoformat()
    assert body["aligned_end"] == full_dates[69].isoformat()


def test_ticker_with_exactly_two_bars_spanning_a_gap_is_insufficient_not_unavailable(
    api_client: TestClient, session: Session
) -> None:
    """Pathological edge case: one ticker has exactly 2 price bars, and the
    one possible adjacency between them spans a missing XNYS session - an
    empty gap-filtered return series despite >= 2 bars actually being
    persisted. RA-03: price history is not missing, so this must report
    `insufficient_observations` / `observations_used: 0` (consistent with how
    services.analytics already reports the identical situation), never
    `unavailable`/`missing_price_history`, and never raise."""
    good = _sec(session, "GOODCO", "Good Co.")
    _insert_bars(session, good, "tiingo", 70)
    twogap = _sec(session, "TWOGAP", "Two Bar Gap Co.")
    full_dates = _bdates(3)
    for day, value in zip([full_dates[0], full_dates[2]], [100.0, 101.0], strict=True):
        session.add(
            PriceBar(
                security_id=twogap,
                trade_date=day,
                source="tiingo",
                close=Decimal("999"),
                adj_close=Decimal(str(value)),
            )
        )
    session.flush()

    body = _get(api_client, tickers="GOODCO,TWOGAP")
    assert body["status"] == "insufficient_observations"
    assert body["observations_used"] == 0
    assert body["required"] == 60
    assert body["unavailable_tickers"] is None


def test_two_ticker_comparison_ok(api_client: TestClient, universe: dict[str, Any]) -> None:
    body = _get(api_client, tickers="AAPL,MSFT")
    assert body["status"] == "ok"
    assert body["tickers"] == ["AAPL", "MSFT"]
    assert body["source"] == "tiingo"
    assert body["adjustment_basis"] == "adjusted_close"
    assert body["observations_used"] == 99
    assert body["aligned_start"] is not None
    assert body["aligned_end"] is not None
    assert body["reason"] is None
    assert body["unavailable_tickers"] is None

    norm = body["normalized_performance"]
    assert len(norm["dates"]) == 100  # observations_used + 1 anchor
    assert norm["dates"][0] is None
    assert norm["series"]["AAPL"][0] == pytest.approx(100.0)
    assert norm["series"]["MSFT"][0] == pytest.approx(100.0)
    assert norm["base_value"] == pytest.approx(100.0)

    corr = body["correlation"]
    assert corr["tickers"] == ["AAPL", "MSFT"]
    assert corr["matrix"][0][0] == pytest.approx(1.0)
    assert corr["matrix"][1][1] == pytest.approx(1.0)
    assert corr["matrix"][0][1] == pytest.approx(corr["matrix"][1][0])


def test_three_ticker_comparison_ok(api_client: TestClient, universe: dict[str, Any]) -> None:
    body = _get(api_client, tickers="AAPL,MSFT,NVDA")
    assert body["status"] == "ok"
    assert body["tickers"] == ["AAPL", "MSFT", "NVDA"]
    assert len(body["correlation"]["matrix"]) == 3
    assert all(len(row) == 3 for row in body["correlation"]["matrix"])


def test_ticker_order_matches_the_request(api_client: TestClient, universe: dict[str, Any]) -> None:
    body = _get(api_client, tickers="NVDA,AAPL,MSFT")
    assert body["tickers"] == ["NVDA", "AAPL", "MSFT"]
    assert body["correlation"]["tickers"] == ["NVDA", "AAPL", "MSFT"]


def test_duplicate_tickers_are_deterministically_deduplicated(
    api_client: TestClient, universe: dict[str, Any]
) -> None:
    body = _get(api_client, tickers="AAPL,AAPL,MSFT")
    assert body["tickers"] == ["AAPL", "MSFT"]


def test_fewer_than_two_distinct_tickers_is_422(
    api_client: TestClient, universe: dict[str, Any]
) -> None:
    assert api_client.get("/compare", params={"tickers": "AAPL"}).status_code == 422
    assert api_client.get("/compare", params={"tickers": "AAPL,AAPL"}).status_code == 422


def test_more_than_eight_tickers_is_422(api_client: TestClient, universe: dict[str, Any]) -> None:
    resp = api_client.get("/compare", params={"tickers": ",".join([f"T{i}" for i in range(9)])})
    assert resp.status_code == 422


def test_unknown_ticker_is_404(api_client: TestClient, universe: dict[str, Any]) -> None:
    resp = api_client.get("/compare", params={"tickers": "AAPL,ZZZZ"})
    assert resp.status_code == 404


def test_start_after_end_is_422(api_client: TestClient, universe: dict[str, Any]) -> None:
    resp = api_client.get(
        "/compare", params={"tickers": "AAPL,MSFT", "start": "2024-06-01", "end": "2024-01-01"}
    )
    assert resp.status_code == 422


def test_missing_price_history_is_unavailable(
    api_client: TestClient, universe: dict[str, Any]
) -> None:
    body = _get(api_client, tickers="AAPL,NOHIST")
    assert body["status"] == "unavailable"
    assert body["reason"] == "missing_price_history"
    assert body["unavailable_tickers"] == ["NOHIST"]
    assert body["normalized_performance"] is None
    assert body["correlation"] is None
    assert body["aligned_start"] is None
    assert body["observations_used"] is None


def test_thin_overlap_is_insufficient_observations(
    api_client: TestClient, universe: dict[str, Any]
) -> None:
    body = _get(api_client, tickers="AAPL,SHORTY")
    assert body["status"] == "insufficient_observations"
    assert body["required"] == 60
    assert body["observations_used"] == 9  # 10 bars -> 9 aligned returns
    assert body["normalized_performance"] is None


def test_source_is_never_merged(api_client: TestClient, universe: dict[str, Any]) -> None:
    # AAPL also has 5 bars under "stooq" (inserted by the `universe` fixture);
    # the default tiingo-sourced comparison must never merge them in.
    body = _get(api_client, tickers="AAPL,MSFT")
    assert body["source"] == "tiingo"
    assert body["status"] == "ok"
    assert body["observations_used"] == 99  # AAPL/MSFT's 100 tiingo bars each


def test_stooq_source_is_rejected_for_compare(
    api_client: TestClient, universe: dict[str, Any]
) -> None:
    # QS-06: Stooq's single, ambiguous Close has no documented adjustment rule
    # (ADR 0022) - rejected at request validation, never silently compared.
    resp = api_client.get("/compare", params={"tickers": "AAPL,MSFT", "source": "stooq"})
    assert resp.status_code == 422


def test_configured_stooq_default_is_rejected_when_source_is_omitted(
    api_client: TestClient,
    universe: dict[str, Any],
    configured_stooq_provider: None,
) -> None:
    # RA-02: an explicit source=stooq is already a 422 (above); a deployment
    # configured with QUANTSCOPE_PRICE_PROVIDER=stooq must not reach /compare
    # by simply omitting `source`, inheriting Stooq through the settings
    # fallback FastAPI's query-parameter validation never sees.
    resp = api_client.get("/compare", params={"tickers": "AAPL,MSFT"})
    assert resp.status_code == 422
    assert "stooq" in resp.json()["detail"].lower()


def test_requested_dates_propagate(api_client: TestClient, universe: dict[str, Any]) -> None:
    dates: list[datetime.date] = universe["aapl_dates"]
    start, end = dates[10], dates[50]
    body = _get(api_client, tickers="AAPL,MSFT", start=start.isoformat(), end=end.isoformat())
    assert body["requested_start"] == start.isoformat()
    assert body["requested_end"] == end.isoformat()


def test_undefined_correlation_serializes_as_json_null_not_nan(
    api_client: TestClient, universe: dict[str, Any]
) -> None:
    resp = api_client.get("/compare", params={"tickers": "AAPL,FLATCO"})
    assert resp.status_code == 200
    assert "NaN" not in resp.text  # never Python's non-standard JSON NaN literal
    body = json.loads(resp.text)  # strict JSON parse - would raise on a bare NaN
    assert body["status"] == "ok"
    assert body["zero_variance_tickers"] == ["FLATCO"]
    corr = body["correlation"]
    flat_idx = corr["tickers"].index("FLATCO")
    assert corr["matrix"][flat_idx][flat_idx] is None  # own diagonal, 0/0 - not 1.0
    for row in corr["matrix"]:
        assert row[flat_idx] is None or row.index(row[flat_idx]) >= 0  # every FLATCO cell is null
    aapl_idx = corr["tickers"].index("AAPL")
    assert corr["matrix"][aapl_idx][flat_idx] is None
    assert corr["matrix"][aapl_idx][aapl_idx] == pytest.approx(1.0)


def test_openapi_describes_correlation_and_dates_as_nullable_not_strings(
    api_client: TestClient,
) -> None:
    schemas = api_client.get("/openapi.json").json()["components"]["schemas"]

    matrix_items = schemas["CorrelationMatrix"]["properties"]["matrix"]["items"]["items"]
    matrix_types = {v.get("type") for v in matrix_items.get("anyOf", [matrix_items])}
    assert matrix_types == {"number", "null"}

    dates_items = schemas["NormalizedPerformance"]["properties"]["dates"]["items"]
    dates_types = {v.get("type") for v in dates_items.get("anyOf", [dates_items])}
    assert dates_types == {"string", "null"}


def test_phase_1e_and_2b_endpoints_unchanged(
    api_client: TestClient, universe: dict[str, Any]
) -> None:
    assert api_client.get("/securities/AAPL").json()["ticker"] == "AAPL"
    assert api_client.get("/securities/AAPL/analytics").status_code == 200
    assert api_client.get("/securities", params={"q": "AAPL"}).status_code == 200
