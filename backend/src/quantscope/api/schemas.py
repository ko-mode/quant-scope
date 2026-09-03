"""Pydantic response models for the read-only securities/prices API (Phase 1E).

Kept separate from the SQLAlchemy ORM models: these describe the *wire* shape.
Price fields stay ``Decimal`` through validation and ``model_dump()`` (python
mode) - exact ``NUMERIC(18, 6)`` end to end in the domain - and are converted to
``float`` only when serialising to **JSON** (``when_used="json"``), so the HTTP
response and the OpenAPI schema present them as numbers (``"close": 100.1``).
That is the precision the quant engine already works in; a decimal *string* would
force every JS/chart consumer to parse. ``security.id`` and
``price_bar.ingested_at`` are deliberately not exposed.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_serializer

#: Price providers the API accepts as a ``source`` filter - the set
#: ``quantscope.data.ingest.build_price_provider`` knows. An unknown value is a
#: 422 at request validation.
PriceSource = Literal["tiingo", "stooq"]


class SecurityRead(BaseModel):
    """One security as the search list and the detail endpoint both return it."""

    model_config = ConfigDict(from_attributes=True)

    ticker: str
    name: str
    exchange: str
    currency: str
    asset_type: str | None
    is_active: bool
    first_trade_date: datetime.date | None
    last_trade_date: datetime.date | None
    delisted_date: datetime.date | None


class SecurityListResponse(BaseModel):
    results: list[SecurityRead]
    limit: int
    offset: int
    count: int  # rows in this page (not a universe-wide total)


class PriceBarRead(BaseModel):
    """One persisted daily bar. ``close`` is raw; ``adj_close`` is vendor-adjusted.

    ``open/high/low/close/adj_close`` stay ``Decimal`` (exact ``NUMERIC(18, 6)``);
    the JSON serialisers below emit them as numbers. Split into a required and a
    nullable serialiser so the serialisation/OpenAPI schema is exactly
    ``number`` vs ``number | null`` per field.
    """

    model_config = ConfigDict(from_attributes=True)

    trade_date: datetime.date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    adj_close: Decimal
    volume: int | None
    source: str

    @field_serializer("close", "adj_close", when_used="json")
    def _serialize_required_price(self, value: Decimal) -> float:
        return float(value)

    @field_serializer("open", "high", "low", when_used="json")
    def _serialize_optional_price(self, value: Decimal | None) -> float | None:
        return None if value is None else float(value)


class PriceHistoryResponse(BaseModel):
    ticker: str
    source: str  # the resolved source (may have been defaulted)
    start: datetime.date | None
    end: datetime.date | None
    limit: int
    offset: int
    count: int
    results: list[PriceBarRead]


__all__ = [
    "PriceBarRead",
    "PriceHistoryResponse",
    "PriceSource",
    "SecurityListResponse",
    "SecurityRead",
]
