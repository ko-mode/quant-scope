"""Asset-type classification is curated-only - no inference."""

from __future__ import annotations

import pytest

from quantscope.data.reference import classify_asset_type


@pytest.mark.parametrize("ticker", ["SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "IVV"])
def test_curated_etfs_are_etf(ticker: str) -> None:
    assert classify_asset_type(ticker) == "etf"


@pytest.mark.parametrize("ticker", ["AAPL", "NVDA", "JPM", "BRK-B", "spy", "SPYX"])
def test_everything_else_is_undetermined(ticker: str) -> None:
    assert classify_asset_type(ticker) is None
