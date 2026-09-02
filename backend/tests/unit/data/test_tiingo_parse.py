"""Tiingo adapter: JSON parsing, field mapping, HTTP error handling.

Synthetic hand-authored payloads only - no fetched Tiingo data (ADR 0015).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from quantscope.data.providers.base import (
    PriceDataUnavailableError,
    PriceProviderAuthError,
    PriceProviderConfigError,
    PriceProviderError,
    PriceProviderRateLimitedError,
)
from quantscope.data.providers.tiingo import TiingoDailyPriceProvider, parse_tiingo_eod
from quantscope.data.validation import normalize_and_validate

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "prices"
_SAMPLE = json.loads((_FIXTURES / "tiingo_nvda_sample.json").read_text())
_TOKEN = "test-token"  # not a real secret


def _client(
    *, json_body: object = None, text: str | None = None, status: int = 200
) -> httpx.Client:
    def handler(_request: httpx.Request) -> httpx.Response:
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=json_body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _raising_client(exc: Exception) -> httpx.Client:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise exc

    return httpx.Client(transport=httpx.MockTransport(handler))


# --------------------------------------------------------------------------- #
# parse_tiingo_eod - pure
# --------------------------------------------------------------------------- #
def test_maps_fields_and_strips_date_zone() -> None:
    bars = parse_tiingo_eod(_SAMPLE)
    assert len(bars) == len(_SAMPLE)
    first = bars[0]
    assert first.trade_date == "2020-01-02"  # "T00:00:00.000Z" dropped
    assert first.open == "10.0"
    assert first.high == "10.4"
    assert first.low == "9.9"
    assert first.close == "10.2"  # from `close`
    assert first.adj_close == "9.28"  # from `adjClose`
    assert first.volume == "1000000"  # from `volume`, not `adjVolume`


def test_raw_close_and_adj_close_stay_distinct() -> None:
    bars = parse_tiingo_eod(_SAMPLE)
    assert all(b.close != b.adj_close for b in bars)
    # never substituted: the split row keeps its ~halved raw close
    split_row = bars[6]
    assert split_row.close == "5.85"
    assert split_row.adj_close == "10.64"


def test_missing_optional_fields_become_none() -> None:
    bars = parse_tiingo_eod(_SAMPLE)
    assert bars[3].open is None  # fixture row omits "open"
    assert bars[5].volume is None  # fixture row omits "volume"
    # required fields on those rows are still present
    assert bars[3].close == "11.0" and bars[3].adj_close == "10.0"


@pytest.mark.parametrize(
    "payload",
    [
        {"detail": "Error: Ticker 'ZZZZ' not found."},
        [],
    ],
)
def test_empty_or_detail_payload_raises_unavailable(payload: object) -> None:
    with pytest.raises(PriceDataUnavailableError):
        parse_tiingo_eod(payload)


@pytest.mark.parametrize("payload", ['{"not": "a list"}', "42", '["not-an-object"]'])
def test_structurally_malformed_payload_raises_provider_error(payload: str) -> None:
    with pytest.raises(PriceProviderError):
        parse_tiingo_eod(json.loads(payload))


# --------------------------------------------------------------------------- #
# adapter -> existing normalization + Pandera validation
# --------------------------------------------------------------------------- #
def test_adapter_output_passes_existing_normalization_and_validation() -> None:
    provider = TiingoDailyPriceProvider(token=_TOKEN, client=_client(json_body=_SAMPLE))
    bars = provider.fetch_daily_history("NVDA", start=date(2020, 1, 1), end=date(2020, 1, 31))

    result = normalize_and_validate(bars, source=provider.source_name)
    assert result.ok, result.error_counts
    frame = result.valid
    assert len(frame) == len(_SAMPLE)
    assert list(frame["source"].unique()) == ["tiingo"]
    # raw vs adjusted preserved end-to-end
    assert (frame["close"] != frame["adj_close"]).all()
    assert (frame["close"] > 0).all() and (frame["adj_close"] > 0).all()
    assert frame["trade_date"].is_monotonic_increasing
    assert frame["trade_date"].is_unique


# --------------------------------------------------------------------------- #
# configuration + HTTP error mapping
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("token", ["", "   ", None])
def test_missing_token_raises_config_error(token: str | None) -> None:
    with pytest.raises(PriceProviderConfigError) as exc:
        TiingoDailyPriceProvider(token=token)  # type: ignore[arg-type]
    assert "QUANTSCOPE_TIINGO_TOKEN" in str(exc.value)


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_maps_to_auth_error(status: int) -> None:
    provider = TiingoDailyPriceProvider(
        token=_TOKEN, client=_client(json_body={"detail": "Not authorized."}, status=status)
    )
    with pytest.raises(PriceProviderAuthError):
        provider.fetch_daily_history("NVDA", start=date(2024, 1, 1), end=date(2024, 2, 1))


def test_unknown_ticker_404_maps_to_unavailable() -> None:
    provider = TiingoDailyPriceProvider(token=_TOKEN, client=_client(text="Not found", status=404))
    with pytest.raises(PriceDataUnavailableError):
        provider.fetch_daily_history("ZZZZ", start=date(2024, 1, 1), end=date(2024, 2, 1))


def test_rate_limit_429_maps_to_rate_limited() -> None:
    provider = TiingoDailyPriceProvider(token=_TOKEN, client=_client(text="", status=429))
    with pytest.raises(PriceProviderRateLimitedError):
        provider.fetch_daily_history("NVDA", start=date(2024, 1, 1), end=date(2024, 2, 1))


def test_non_json_response_maps_to_provider_error() -> None:
    provider = TiingoDailyPriceProvider(
        token=_TOKEN, client=_client(text="<html>gateway timeout</html>", status=200)
    )
    with pytest.raises(PriceProviderError):
        provider.fetch_daily_history("NVDA", start=date(2024, 1, 1), end=date(2024, 2, 1))


def test_empty_json_array_maps_to_unavailable() -> None:
    provider = TiingoDailyPriceProvider(token=_TOKEN, client=_client(json_body=[], status=200))
    with pytest.raises(PriceDataUnavailableError):
        provider.fetch_daily_history("NVDA", start=date(2024, 1, 1), end=date(2024, 2, 1))


def test_network_failure_maps_to_provider_error_not_httpx() -> None:
    provider = TiingoDailyPriceProvider(
        token=_TOKEN, client=_raising_client(httpx.ConnectError("name resolution failed"))
    )
    with pytest.raises(PriceProviderError) as exc:
        provider.fetch_daily_history("NVDA", start=date(2024, 1, 1), end=date(2024, 2, 1))
    assert not isinstance(exc.value, httpx.HTTPError)
