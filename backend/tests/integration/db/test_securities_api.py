"""PostgreSQL-backed tests for the Phase 1E read-only API.

Skipped unless ``QUANTSCOPE_TEST_DATABASE_URL`` is set (see conftest). Data is
synthetic - inserted directly into the migrated schema; no SEC / Tiingo access.
The ``api_client`` fixture routes the app's DB session through the test's
rolled-back transaction.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from quantscope.db.models import PriceBar, Security

D = Decimal


def _sec(session: Session, ticker: str, name: str, **kw: object) -> Security:
    security = Security(ticker=ticker, name=name, exchange=kw.pop("exchange", "XNAS"), **kw)
    session.add(security)
    session.flush()
    return security


def _bar(
    session: Session,
    security_id: int,
    day: datetime.date,
    source: str,
    close: Decimal,
    adj_close: Decimal,
    *,
    open_: Decimal | None = None,
    high: Decimal | None = None,
    low: Decimal | None = None,
    volume: int | None = None,
) -> None:
    session.add(
        PriceBar(
            security_id=security_id,
            trade_date=day,
            source=source,
            open=open_,
            high=high,
            low=low,
            close=close,
            adj_close=adj_close,
            volume=volume,
        )
    )


@pytest.fixture
def universe(session: Session) -> dict[str, int]:
    """Five securities; NVDA has tiingo (4) + stooq (2) daily bars in 2024."""
    nvda = _sec(
        session,
        "NVDA",
        "NVIDIA Corporation",
        asset_type="common_stock",
        first_trade_date=datetime.date(1999, 1, 22),
        last_trade_date=datetime.date(2024, 12, 31),
    )
    _sec(session, "AMD", "Advanced Micro Devices, Inc.", asset_type="common_stock")
    _sec(session, "INTC", "Intel Corporation", asset_type=None)
    _sec(session, "NVDAX", "NVDA Special Situations Fund", asset_type="etf")
    _sec(
        session,
        "OLDCO",
        "Old Company (Delisted)",
        asset_type="common_stock",
        is_active=False,
        delisted_date=datetime.date(2020, 5, 1),
    )
    session.flush()
    nvda_id = nvda.id

    _bar(
        session,
        nvda_id,
        datetime.date(2024, 1, 2),
        "tiingo",
        D("100.10"),
        D("95.20"),
        open_=D("99.00"),
        high=D("101.00"),
        low=D("98.50"),
        volume=1_000,
    )
    _bar(
        session, nvda_id, datetime.date(2024, 1, 3), "tiingo", D("102.30"), D("97.10")
    )  # no OHL, no volume
    _bar(
        session,
        nvda_id,
        datetime.date(2024, 6, 10),
        "tiingo",
        D("120.68"),
        D("120.68"),
        volume=3_000,
    )
    _bar(
        session,
        nvda_id,
        datetime.date(2024, 12, 31),
        "tiingo",
        D("140.55"),
        D("140.55"),
        volume=4_000,
    )
    # same security + dates, different provider, deliberately different close
    _bar(session, nvda_id, datetime.date(2024, 1, 2), "stooq", D("100.15"), D("100.15"))
    _bar(session, nvda_id, datetime.date(2024, 6, 10), "stooq", D("120.70"), D("120.70"))

    session.commit()
    return {"NVDA": nvda_id}


# =========================================================================== #
# GET /securities
# =========================================================================== #
def test_search_exact_ticker_is_listed_first(
    api_client: TestClient, universe: dict[str, int]
) -> None:
    body = api_client.get("/securities", params={"q": "NVDA"}).json()
    tickers = [r["ticker"] for r in body["results"]]
    assert tickers == ["NVDA", "NVDAX"]  # exact match first, then ticker ASC
    assert body["count"] == 2
    assert "id" not in body["results"][0]


def test_search_is_case_insensitive(api_client: TestClient, universe: dict[str, int]) -> None:
    lower = api_client.get("/securities", params={"q": "nvda"}).json()
    upper = api_client.get("/securities", params={"q": "NVDA"}).json()
    assert (
        [r["ticker"] for r in lower["results"]]
        == [r["ticker"] for r in upper["results"]]
        == [
            "NVDA",
            "NVDAX",
        ]
    )


def test_search_partial_ticker(api_client: TestClient, universe: dict[str, int]) -> None:
    body = api_client.get("/securities", params={"q": "nvd"}).json()
    assert [r["ticker"] for r in body["results"]] == ["NVDA", "NVDAX"]


def test_search_by_company_name(api_client: TestClient, universe: dict[str, int]) -> None:
    body = api_client.get("/securities", params={"q": "advanced micro"}).json()
    assert [r["ticker"] for r in body["results"]] == ["AMD"]


def test_search_ordering_is_deterministic(api_client: TestClient, universe: dict[str, int]) -> None:
    first = api_client.get("/securities", params={"q": "nvd"}).json()
    second = api_client.get("/securities", params={"q": "nvd"}).json()
    assert first["results"] == second["results"]
    assert [r["ticker"] for r in first["results"]] == sorted(r["ticker"] for r in first["results"])


def test_search_without_query_returns_bounded_sorted_page(
    api_client: TestClient, universe: dict[str, int]
) -> None:
    body = api_client.get("/securities").json()
    tickers = [r["ticker"] for r in body["results"]]
    assert tickers == ["AMD", "INTC", "NVDA", "NVDAX", "OLDCO"]
    assert body["limit"] == 50 and body["offset"] == 0


def test_search_limit_and_offset(api_client: TestClient, universe: dict[str, int]) -> None:
    page1 = api_client.get("/securities", params={"q": "nvd", "limit": 1}).json()
    assert [r["ticker"] for r in page1["results"]] == ["NVDA"]
    assert page1["count"] == 1 and page1["limit"] == 1

    page2 = api_client.get("/securities", params={"q": "nvd", "limit": 1, "offset": 1}).json()
    assert [r["ticker"] for r in page2["results"]] == ["NVDAX"]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"limit": "abc"}, {"offset": -1}])
def test_search_rejects_bad_pagination(
    api_client: TestClient, universe: dict[str, int], params: dict[str, str | int]
) -> None:
    assert api_client.get("/securities", params=params).status_code == 422


def test_search_includes_inactive_security_with_flags(
    api_client: TestClient, universe: dict[str, int]
) -> None:
    body = api_client.get("/securities", params={"q": "old company"}).json()
    assert len(body["results"]) == 1
    row = body["results"][0]
    assert row["ticker"] == "OLDCO"
    assert row["is_active"] is False
    assert row["delisted_date"] == "2020-05-01"


def test_search_no_match_is_empty_200(api_client: TestClient, universe: dict[str, int]) -> None:
    resp = api_client.get("/securities", params={"q": "ZZZZZZ"})
    assert resp.status_code == 200
    assert resp.json() == {"results": [], "limit": 50, "offset": 0, "count": 0}


# =========================================================================== #
# GET /securities/{ticker}
# =========================================================================== #
def test_detail_success(api_client: TestClient, universe: dict[str, int]) -> None:
    body = api_client.get("/securities/NVDA").json()
    assert body["ticker"] == "NVDA"
    assert body["name"] == "NVIDIA Corporation"
    assert body["currency"] == "USD"
    assert body["first_trade_date"] == "1999-01-22"
    assert "id" not in body


def test_detail_normalizes_lowercase(api_client: TestClient, universe: dict[str, int]) -> None:
    assert api_client.get("/securities/nvda").json()["ticker"] == "NVDA"


def test_detail_nullable_asset_type(api_client: TestClient, universe: dict[str, int]) -> None:
    assert api_client.get("/securities/INTC").json()["asset_type"] is None


def test_detail_unknown_ticker_404(api_client: TestClient, universe: dict[str, int]) -> None:
    resp = api_client.get("/securities/ZZZZ")
    assert resp.status_code == 404
    assert "ZZZZ" in resp.json()["detail"]


def test_detail_malformed_ticker_404_not_fuzzy(
    api_client: TestClient, universe: dict[str, int]
) -> None:
    assert api_client.get("/securities/@@@").status_code == 404


# =========================================================================== #
# GET /securities/{ticker}/prices
# =========================================================================== #
def test_prices_returns_rows_ascending_with_expected_shape(
    api_client: TestClient, universe: dict[str, int]
) -> None:
    body = api_client.get("/securities/NVDA/prices", params={"source": "tiingo"}).json()
    assert body["source"] == "tiingo"
    assert body["count"] == 4
    dates = [r["trade_date"] for r in body["results"]]
    assert dates == ["2024-01-02", "2024-01-03", "2024-06-10", "2024-12-31"]
    assert dates == sorted(dates)

    row0, row1 = body["results"][0], body["results"][1]
    assert set(row0) == {
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
        "source",
    }
    assert "ingested_at" not in row0
    assert row0["open"] == 99.0 and row0["volume"] == 1_000
    assert row1["open"] is None and row1["volume"] is None  # nullable columns -> JSON null


def test_prices_serialize_as_json_numbers(api_client: TestClient, universe: dict[str, int]) -> None:
    rows = api_client.get("/securities/NVDA/prices", params={"source": "tiingo"}).json()["results"]
    row0, row1 = rows[0], rows[1]

    # non-null OHLC / adj_close cross the wire as JSON numbers, never strings
    for field in ("open", "high", "low", "close", "adj_close"):
        value = row0[field]
        assert isinstance(value, float) and not isinstance(value, bool), (field, value)

    # representative 6-decimal values survive within float tolerance
    assert row0["open"] == pytest.approx(99.0)
    assert row0["high"] == pytest.approx(101.0)
    assert row0["low"] == pytest.approx(98.5)
    assert row0["close"] == pytest.approx(100.10)
    assert row0["adj_close"] == pytest.approx(95.20)

    # a clean value still renders without float noise
    assert json.dumps(row0["close"]) == "100.1"

    # nullable price fields still serialise as JSON null
    assert row1["open"] is None and row1["high"] is None and row1["low"] is None

    # volume stays an integer
    assert isinstance(row0["volume"], int) and not isinstance(row0["volume"], bool)
    assert row0["volume"] == 1_000


def test_openapi_schema_describes_prices_as_numbers_not_strings(api_client: TestClient) -> None:
    """Phase 1F's generated TS client must see open/high/low/close/adj_close as number."""
    props = api_client.get("/openapi.json").json()["components"]["schemas"]["PriceBarRead"][
        "properties"
    ]

    for field in ("close", "adj_close"):  # required -> plain number
        assert props[field].get("type") == "number", (field, props[field])

    for field in ("open", "high", "low"):  # nullable -> number | null, never string
        variants = props[field].get("anyOf", [props[field]])
        types = {v.get("type") for v in variants}
        assert types == {"number", "null"}, (field, props[field])

    volume_types = {v.get("type") for v in props["volume"].get("anyOf", [props["volume"]])}
    assert volume_types == {"integer", "null"}


def test_prices_start_filter(api_client: TestClient, universe: dict[str, int]) -> None:
    body = api_client.get(
        "/securities/NVDA/prices", params={"source": "tiingo", "start": "2024-06-01"}
    ).json()
    assert [r["trade_date"] for r in body["results"]] == ["2024-06-10", "2024-12-31"]


def test_prices_end_filter(api_client: TestClient, universe: dict[str, int]) -> None:
    body = api_client.get(
        "/securities/NVDA/prices", params={"source": "tiingo", "end": "2024-01-31"}
    ).json()
    assert [r["trade_date"] for r in body["results"]] == ["2024-01-02", "2024-01-03"]


def test_prices_combined_date_range(api_client: TestClient, universe: dict[str, int]) -> None:
    body = api_client.get(
        "/securities/NVDA/prices",
        params={"source": "tiingo", "start": "2024-01-01", "end": "2024-06-30"},
    ).json()
    assert [r["trade_date"] for r in body["results"]] == [
        "2024-01-02",
        "2024-01-03",
        "2024-06-10",
    ]


def test_prices_exact_source_filtering(api_client: TestClient, universe: dict[str, int]) -> None:
    body = api_client.get("/securities/NVDA/prices", params={"source": "stooq"}).json()
    assert body["count"] == 2
    assert {r["source"] for r in body["results"]} == {"stooq"}
    assert [r["close"] for r in body["results"]] == pytest.approx([100.15, 120.70])


def test_prices_sources_never_merged(api_client: TestClient, universe: dict[str, int]) -> None:
    tiingo = api_client.get("/securities/NVDA/prices", params={"source": "tiingo"}).json()
    stooq = api_client.get("/securities/NVDA/prices", params={"source": "stooq"}).json()
    assert tiingo["count"] == 4 and stooq["count"] == 4 - 2  # distinct series, not combined

    # 2024-01-02 exists in both with different closes; each response carries only its own
    tiingo_0102 = next(r for r in tiingo["results"] if r["trade_date"] == "2024-01-02")
    stooq_0102 = next(r for r in stooq["results"] if r["trade_date"] == "2024-01-02")
    assert tiingo_0102["close"] == pytest.approx(100.10)
    assert stooq_0102["close"] == pytest.approx(100.15)
    assert all(r["source"] == "tiingo" for r in tiingo["results"])


def test_prices_default_source_is_configured_provider(
    api_client: TestClient, universe: dict[str, int]
) -> None:
    body = api_client.get("/securities/NVDA/prices").json()  # no ?source
    assert body["source"] == "tiingo"  # settings.price_provider default
    assert body["count"] == 4
    assert all(r["close"] != pytest.approx(100.15) for r in body["results"])  # no stooq rows


def test_prices_unknown_ticker_404(api_client: TestClient, universe: dict[str, int]) -> None:
    assert api_client.get("/securities/ZZZZ/prices").status_code == 404


def test_prices_existing_security_no_bars_is_empty_200(
    api_client: TestClient, universe: dict[str, int]
) -> None:
    resp = api_client.get("/securities/AMD/prices", params={"source": "tiingo"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"] == [] and body["count"] == 0

    out_of_range = api_client.get(
        "/securities/NVDA/prices",
        params={"source": "tiingo", "start": "2030-01-01", "end": "2030-12-31"},
    ).json()
    assert out_of_range["results"] == []


def test_prices_start_after_end_is_422(api_client: TestClient, universe: dict[str, int]) -> None:
    resp = api_client.get(
        "/securities/NVDA/prices", params={"start": "2024-12-31", "end": "2024-01-01"}
    )
    assert resp.status_code == 422
    assert "after end" in resp.json()["detail"]


def test_prices_unknown_source_is_422(api_client: TestClient, universe: dict[str, int]) -> None:
    assert (
        api_client.get("/securities/NVDA/prices", params={"source": "bloomberg"}).status_code == 422
    )


@pytest.mark.parametrize("params", [{"start": "not-a-date"}, {"limit": 0}, {"limit": 99_999}])
def test_prices_rejects_bad_params(
    api_client: TestClient, universe: dict[str, int], params: dict[str, str | int]
) -> None:
    params.setdefault("source", "tiingo")
    assert api_client.get("/securities/NVDA/prices", params=params).status_code == 422
