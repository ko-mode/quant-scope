"""Provider-agnostic contracts for security reference data.

A provider's only job is to return the source's rows as strings/None with no
interpretation. All decisions about validity, formatting and classification
happen later, in ``quantscope.data.reference``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


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
