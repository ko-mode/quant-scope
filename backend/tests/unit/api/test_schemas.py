"""`resolve_quantitative_source` - the RA-02 configured-default Stooq fix.

QS-06 restricted the `source` *query parameter* on analytics/compare/factors
to `Literal["tiingo"]`, but every one of those routers falls back to
`get_settings().price_provider` - a plain, unconstrained string - when
`source` is omitted. FastAPI's request validation never sees that fallback
value, so a deployment configured with `QUANTSCOPE_PRICE_PROVIDER=stooq`
could previously reach every return-based analytics endpoint by simply never
passing `source`. These tests exercise `resolve_quantitative_source` in
isolation, independent of any HTTP request, database, or FastAPI dependency
wiring - the API-level regression is covered separately in
`tests/integration/db/test_{analytics,comparison,factors}_api.py`.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from quantscope.api import schemas
from quantscope.config import Settings


def _settings(price_provider: str) -> Settings:
    return Settings(price_provider=price_provider)


def test_explicit_tiingo_is_returned_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    # An explicit, already-FastAPI-validated `source` always wins over
    # whatever the configured default provider happens to be.
    monkeypatch.setattr(schemas, "get_settings", lambda: _settings("stooq"))
    assert schemas.resolve_quantitative_source("tiingo") == "tiingo"


def test_omitted_source_falls_back_to_a_valid_configured_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(schemas, "get_settings", lambda: _settings("tiingo"))
    assert schemas.resolve_quantitative_source(None) == "tiingo"


def test_omitted_source_with_a_configured_stooq_default_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # RA-02: the exact path QS-06's query-parameter-only Literal left open -
    # `source` omitted, the configured default provider is Stooq.
    monkeypatch.setattr(schemas, "get_settings", lambda: _settings("stooq"))
    with pytest.raises(HTTPException) as exc_info:
        schemas.resolve_quantitative_source(None)
    assert exc_info.value.status_code == 422
    assert "stooq" in str(exc_info.value.detail).lower()


def test_an_unrecognised_configured_provider_is_also_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Not just Stooq specifically - any provider outside `QuantitativeSource`
    # is rejected the same way, so this never grows into a provider-specific
    # special case.
    monkeypatch.setattr(schemas, "get_settings", lambda: _settings("some_future_provider"))
    with pytest.raises(HTTPException) as exc_info:
        schemas.resolve_quantitative_source(None)
    assert exc_info.value.status_code == 422
