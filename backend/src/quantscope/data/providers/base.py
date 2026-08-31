"""Provider-agnostic contracts for external data sources.

A provider's only job is to return a source's rows with values uninterpreted
(``str`` / ``None``). Validity, formatting, classification and adjustment
semantics are decided later, in ``quantscope.data`` - never in a provider and
never in ``quantscope.quant``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

# --------------------------------------------------------------------------- #
# Security reference data (Phase 1B)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class RawSecurityRecord:
    """One security as a source presents it, coerced only to ``str`` / ``None``.

    ``None`` means "the source did not provide this field"; empty strings from
    the source are normalised to ``None`` by the provider.
    """

    ticker: str | None
    name: str | None
    cik: str | None
    exchange: str | None


@runtime_checkable
class SecurityReferenceProvider(Protocol):
    """A source of the security universe (e.g. SEC company/ticker reference data)."""

    #: Stable identifier recorded in ``data_ingestion_run.source``.
    source_name: str

    def fetch_securities(self) -> list[RawSecurityRecord]:
        """Return every record currently published by the source."""
        ...


# --------------------------------------------------------------------------- #
# Daily market prices (Phase 1C)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class RawPriceBar:
    """One daily bar as a provider delivered it - values uninterpreted.

    Every field is the source's text (or ``None`` where the source gave nothing).
    ``adj_close`` is filled by the provider: a source that serves a single price
    series (e.g. Stooq) sets ``adj_close == close`` and documents that choice;
    a source that distinguishes raw and adjusted fills both distinctly.
    """

    trade_date: str | None
    open: str | None
    high: str | None
    low: str | None
    close: str | None
    adj_close: str | None
    volume: str | None


@runtime_checkable
class DailyPriceProvider(Protocol):
    """A source of daily OHLCV history for a single security."""

    #: Stable identifier written to the ``source`` column of every bar.
    source_name: str

    def fetch_daily_history(self, ticker: str, *, start: date, end: date) -> list[RawPriceBar]:
        """Return the provider's daily bars for ``ticker`` within ``[start, end]``.

        Order is not guaranteed; callers sort during normalisation. Raises
        :class:`PriceDataUnavailableError` when the source has nothing for the ticker
        and :class:`PriceProviderRateLimitedError` when throttled.
        """
        ...


class PriceProviderError(RuntimeError):
    """A price provider could not return usable data."""


class PriceDataUnavailableError(PriceProviderError):
    """The provider has no data for the requested ticker / range."""


class PriceProviderRateLimitedError(PriceProviderError):
    """The provider refused the request due to rate limiting."""


class PriceProviderBlockedError(PriceProviderError):
    """The provider served an anti-bot / browser-verification challenge instead of data."""
