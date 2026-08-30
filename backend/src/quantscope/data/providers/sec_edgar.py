"""SEC EDGAR adapter for the security universe.

Source: ``https://www.sec.gov/files/company_tickers_exchange.json`` - a public
file of the form::

    {"fields": ["cik", "name", "ticker", "exchange"],
     "data":   [[320193, "Apple Inc.", "AAPL", "Nasdaq"], ...]}

The file is never committed to the repository (ADR 0015); ``--source-file`` on
the CLI lets a developer point at a locally downloaded copy.

SEC's access policy requires a ``User-Agent`` header identifying the caller with
contact information; it is configured via ``QUANTSCOPE_SEC_USER_AGENT``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from quantscope.data.providers.base import RawSecurityRecord

logger = logging.getLogger(__name__)

SOURCE_NAME = "sec_company_tickers_exchange"
_EXPECTED_FIELDS = ("cik", "name", "ticker", "exchange")
_REQUEST_TIMEOUT = 30.0


class SecReferenceDataError(RuntimeError):
    """The SEC payload did not have the expected ``{fields, data}`` shape."""


def _coerce(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_company_tickers_exchange(payload: object) -> list[RawSecurityRecord]:
    """Turn a parsed ``company_tickers_exchange.json`` document into raw records.

    Columns are located by the ``fields`` header, not by position, so a change
    in SEC's column order does not silently corrupt the mapping.
    """
    if not isinstance(payload, dict) or "fields" not in payload or "data" not in payload:
        raise SecReferenceDataError("expected a JSON object with 'fields' and 'data' keys")

    fields = payload["fields"]
    rows = payload["data"]
    if not isinstance(fields, list) or not isinstance(rows, list):
        raise SecReferenceDataError("'fields' and 'data' must both be arrays")

    try:
        idx = {name: fields.index(name) for name in _EXPECTED_FIELDS}
    except ValueError as exc:
        raise SecReferenceDataError(
            f"'fields' {fields!r} is missing one of {_EXPECTED_FIELDS}"
        ) from exc

    records: list[RawSecurityRecord] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < len(fields):
            logger.warning("sec_edgar.malformed_row", extra={"row": row})
            continue
        records.append(
            RawSecurityRecord(
                ticker=_coerce(row[idx["ticker"]]),
                name=_coerce(row[idx["name"]]),
                cik=_coerce(row[idx["cik"]]),
                exchange=_coerce(row[idx["exchange"]]),
            )
        )
    return records


class SecEdgarSecurityProvider:
    """Fetches the security universe from SEC EDGAR (or a local copy)."""

    source_name = SOURCE_NAME

    def __init__(
        self,
        *,
        user_agent: str,
        url: str = "https://www.sec.gov/files/company_tickers_exchange.json",
        source_file: Path | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._user_agent = user_agent
        self._url = url
        self._source_file = source_file
        self._client = client

    def fetch_securities(self) -> list[RawSecurityRecord]:
        if self._source_file is not None:
            logger.info("sec_edgar.read_file", extra={"path": str(self._source_file)})
            payload = json.loads(self._source_file.read_text(encoding="utf-8"))
        else:
            payload = self._get_json()
        records = parse_company_tickers_exchange(payload)
        logger.info("sec_edgar.fetched", extra={"records": len(records)})
        return records

    def _get_json(self) -> object:
        headers = {"User-Agent": self._user_agent, "Accept": "application/json"}
        logger.info("sec_edgar.http_get", extra={"url": self._url})
        if self._client is not None:
            response = self._client.get(self._url, headers=headers)
        else:
            with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
                response = client.get(self._url, headers=headers)
        response.raise_for_status()
        return response.json()
