"""`build_price_provider` - configured provider construction (no DB, no HTTP)."""

from __future__ import annotations

import pytest

from quantscope.config import Settings
from quantscope.data.ingest import build_price_provider
from quantscope.data.providers.base import PriceProviderConfigError
from quantscope.data.providers.stooq import StooqDailyPriceProvider
from quantscope.data.providers.tiingo import TiingoDailyPriceProvider


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "price_provider": "tiingo",
        "tiingo_api_token": "test-token",
        "tiingo_base_url": "https://api.tiingo.example",
        "stooq_base_url": "https://stooq.example/q/d/l/",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_defaults_to_configured_provider() -> None:
    provider = build_price_provider(_settings(price_provider="tiingo"))
    assert isinstance(provider, TiingoDailyPriceProvider)
    assert provider.source_name == "tiingo"


def test_explicit_name_overrides_config() -> None:
    provider = build_price_provider(_settings(price_provider="tiingo"), "stooq")
    assert isinstance(provider, StooqDailyPriceProvider)
    assert provider.source_name == "stooq"


@pytest.mark.parametrize("name", ["TIINGO", " Tiingo ", "tiingo"])
def test_name_is_case_and_space_insensitive(name: str) -> None:
    assert isinstance(build_price_provider(_settings(), name), TiingoDailyPriceProvider)


def test_tiingo_without_token_raises_config_error() -> None:
    with pytest.raises(PriceProviderConfigError):
        build_price_provider(_settings(tiingo_api_token=""))


def test_unknown_provider_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unknown price provider"):
        build_price_provider(_settings(), "quandl")
