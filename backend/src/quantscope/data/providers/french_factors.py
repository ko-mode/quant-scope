"""Kenneth R. French Data Library adapter - daily Fama/French 3 factors + RF.

Source: ``F-F_Research_Data_Factors_daily_CSV.zip`` (one CSV inside), served from
the Tuck faculty FTP area. The file is:

* one or more free-text preamble lines (a description, sometimes a blank line);
* a header line ``,Mkt-RF,SMB,HML,RF`` (leading empty cell = the date column);
* daily rows ``YYYYMMDD,<pct>,<pct>,<pct>,<pct>`` to EOF;
* possibly trailing blank lines / footer text.

The **daily** file has no "Annual Factors" section (that is monthly-only), but
the parser stops at the first non-data line after the data block regardless, so
a footer is harmless.

Values are in **percent** and are emitted here **uninterpreted** (raw strings),
exactly like :func:`quantscope.data.providers.stooq.parse_stooq_csv`. Date
parsing, the missing-value sentinels (``-99.99`` / ``-999``) and the
percent -> decimal conversion are handled by
:func:`quantscope.data.factors.normalize_factor_returns` (ADR 0009).

No Kenneth French file is committed to the repository (ADR 0015); tests use
synthetic text and a locally supplied ``--source-file``.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from pathlib import Path

import httpx

from quantscope.data.providers.base import (
    FactorDataUnavailableError,
    FactorProviderBlockedError,
    FactorProviderError,
    RawFactorReturn,
)

logger = logging.getLogger(__name__)

SOURCE_NAME = "kenneth_french"
#: Header tokens (lower-cased) that identify the FF3-daily column row.
_FACTOR_TOKENS: tuple[str, ...] = ("mkt-rf", "smb", "hml", "rf")
_DATA_ROW = re.compile(r"^\s*(\d{8})\s*,")
_REQUEST_TIMEOUT = 60.0


def _split(line: str) -> list[str]:
    return [cell.strip() for cell in line.split(",")]


def parse_ff_daily_factors(text: str, source: str = SOURCE_NAME) -> list[RawFactorReturn]:
    """Parse a Kenneth French daily FF3 CSV body into raw (date, factor) records.

    Pure; no I/O. The header row is found structurally (the first line whose
    cells contain all of Mkt-RF / SMB / HML / RF), so the preamble length is
    never assumed.
    """
    lowered = text.lower()
    if "<html" in lowered or "<!doctype" in lowered:
        raise FactorProviderBlockedError(f"{source}: served an HTML page instead of the data file")

    lines = text.splitlines()
    header_idx: int | None = None
    columns: dict[str, int] = {}
    for i, line in enumerate(lines):
        cells = [cell.lower() for cell in _split(line)]
        if all(token in cells for token in _FACTOR_TOKENS):
            header_idx = i
            columns = {
                "mkt_rf": cells.index("mkt-rf"),
                "smb": cells.index("smb"),
                "hml": cells.index("hml"),
                "rf": cells.index("rf"),
            }
            break
    if header_idx is None:
        raise FactorDataUnavailableError(
            f"{source}: no 'Mkt-RF,SMB,HML,RF' header row found in {len(lines)} lines"
        )

    records: list[RawFactorReturn] = []
    started = False
    for line in lines[header_idx + 1 :]:
        if not _DATA_ROW.match(line):
            if started:
                break  # end of the data block (blank line / footer)
            if line.strip() == "":
                continue
            break  # a non-blank, non-data line before any data -> stop
        started = True
        cells = _split(line)
        max_col = max(columns.values())
        if len(cells) <= max_col:
            logger.warning("french_factors.short_row", extra={"row": cells})
            continue
        trade_date = cells[0] or None
        for name, col in columns.items():
            value = cells[col]
            records.append(
                RawFactorReturn(trade_date=trade_date, factor_name=name, value=value or None)
            )

    if not records:
        raise FactorDataUnavailableError(f"{source}: header found but no daily rows followed it")
    return records


def _csv_from_zip(content: bytes, source: str) -> str:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise FactorProviderError(f"{source}: response is not a valid ZIP archive") from exc
    members = [n for n in archive.namelist() if n.lower().endswith(".csv")]
    if not members:
        raise FactorDataUnavailableError(
            f"{source}: ZIP has no .csv member (contains {archive.namelist()!r})"
        )
    return archive.read(members[0]).decode("latin-1")


class KennethFrenchDailyFactorProvider:
    """Fetches the daily FF3 + RF file. Replaceable behind :class:`DailyFactorProvider`."""

    source_name = SOURCE_NAME

    def __init__(
        self,
        *,
        url: str,
        source_file: Path | None = None,
        client: httpx.Client | None = None,
        timeout: float = _REQUEST_TIMEOUT,
    ) -> None:
        self._url = url
        self._source_file = source_file
        self._client = client
        self._timeout = timeout

    def _load_text(self) -> str:
        if self._source_file is not None:
            data = self._source_file.read_bytes()
            if self._source_file.suffix.lower() == ".zip":
                return _csv_from_zip(data, self.source_name)
            return data.decode("latin-1")

        logger.info("french_factors.http_get", extra={"url": self._url})
        try:
            if self._client is not None:
                response = self._client.get(self._url)
            else:
                with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                    response = client.get(self._url)
        except httpx.HTTPError as exc:
            raise FactorProviderError(
                f"{self.source_name}: network error contacting {self._url}: {exc!r}"
            ) from exc

        if response.status_code >= 400:
            raise FactorProviderError(
                f"{self.source_name}: HTTP {response.status_code} for {self._url}"
            )
        return _csv_from_zip(response.content, self.source_name)

    def fetch_daily_factors(self) -> list[RawFactorReturn]:
        records = parse_ff_daily_factors(self._load_text(), self.source_name)
        logger.info("french_factors.fetched", extra={"records": len(records)})
        return records
