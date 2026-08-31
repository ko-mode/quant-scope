"""Normalise raw provider bars into the canonical daily price-bar DataFrame.

Pure pandas - no provider knowledge, no I/O, no database. Turns
``list[RawPriceBar]`` into a typed frame with columns
``trade_date, open, high, low, close, adj_close, volume, source`` (in that
order), and reports rows it had to drop as structured
:class:`PriceValidationError` values.

Policy (ADR 0006, 0012):

* Missing (source gave nothing) is kept as ``NaN`` for open/high/low/volume;
  a missing ``close`` or ``adj_close`` drops the row (``missing_required_value``).
* A non-empty value that will not parse (number or date) drops the row
  (``malformed_numeric`` / ``invalid_trade_date``) - never silently zero-filled.
* ``trade_date`` is a naive ``datetime64[ns]`` at midnight (an XNYS session
  date); the frame is sorted ascending by it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import pandas as pd

from quantscope.data.providers.base import RawPriceBar

PRICE_BAR_COLUMNS: tuple[str, ...] = (
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "source",
)

_PRICE_FIELDS: tuple[str, ...] = ("open", "high", "low", "close", "adj_close")
_REQUIRED_FIELDS: tuple[str, ...] = ("close", "adj_close")


@dataclass(frozen=True, slots=True)
class PriceValidationError:
    """A structured reason a bar is not eligible for persistence."""

    code: str
    detail: str
    column: str | None = None
    trade_date: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "column": self.column,
            "trade_date": self.trade_date,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class NormalizedPrices:
    frame: pd.DataFrame
    parse_errors: tuple[PriceValidationError, ...] = field(default_factory=tuple)


def empty_price_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": pd.Series([], dtype="datetime64[ns]"),
            "open": pd.Series([], dtype="float64"),
            "high": pd.Series([], dtype="float64"),
            "low": pd.Series([], dtype="float64"),
            "close": pd.Series([], dtype="float64"),
            "adj_close": pd.Series([], dtype="float64"),
            "volume": pd.Series([], dtype="Int64"),
            "source": pd.Series([], dtype="string"),
        }
    )


def _raw_str(value: str | None) -> str:
    return "" if value is None else str(value).strip()


def normalize_price_bars(raw: Sequence[RawPriceBar], *, source: str) -> NormalizedPrices:
    if not raw:
        return NormalizedPrices(frame=empty_price_frame())

    original = pd.DataFrame(
        {
            "trade_date": [_raw_str(b.trade_date) for b in raw],
            "open": [_raw_str(b.open) for b in raw],
            "high": [_raw_str(b.high) for b in raw],
            "low": [_raw_str(b.low) for b in raw],
            "close": [_raw_str(b.close) for b in raw],
            "adj_close": [_raw_str(b.adj_close) for b in raw],
            "volume": [_raw_str(b.volume) for b in raw],
        }
    )

    errors: list[PriceValidationError] = []
    drop = pd.Series(False, index=original.index)

    parsed_date = pd.to_datetime(
        original["trade_date"], errors="coerce", format="ISO8601"
    ).dt.normalize()
    bad_date = parsed_date.isna()
    for i in original.index[bad_date]:
        raw_date = str(original.at[i, "trade_date"])
        errors.append(
            PriceValidationError(
                code="invalid_trade_date",
                column="trade_date",
                trade_date=raw_date or None,
                detail=f"unparseable trade_date: {raw_date!r}",
            )
        )
    drop |= bad_date

    numeric: dict[str, pd.Series] = {}
    for col in _PRICE_FIELDS:
        values = pd.to_numeric(original[col], errors="coerce")
        malformed = values.isna() & (original[col] != "")
        for i in original.index[malformed]:
            errors.append(
                PriceValidationError(
                    code="malformed_numeric",
                    column=col,
                    trade_date=_date_label(parsed_date, i),
                    detail=f"unparseable {col}: {original.at[i, col]!r}",
                )
            )
        drop |= malformed
        numeric[col] = values.astype("float64")

    vol_num = pd.to_numeric(original["volume"], errors="coerce")
    vol_malformed = vol_num.isna() & (original["volume"] != "")
    for i in original.index[vol_malformed]:
        errors.append(
            PriceValidationError(
                code="malformed_numeric",
                column="volume",
                trade_date=_date_label(parsed_date, i),
                detail=f"unparseable volume: {original.at[i, 'volume']!r}",
            )
        )
    drop |= vol_malformed
    volume = vol_num.round().astype("Int64")

    for col in _REQUIRED_FIELDS:
        missing = numeric[col].isna() & (original[col] == "") & ~drop
        for i in original.index[missing]:
            errors.append(
                PriceValidationError(
                    code="missing_required_value",
                    column=col,
                    trade_date=_date_label(parsed_date, i),
                    detail=f"{col} is required but missing",
                )
            )
        drop |= missing

    keep = ~drop
    frame = pd.DataFrame(
        {
            "trade_date": parsed_date[keep],
            "open": numeric["open"][keep],
            "high": numeric["high"][keep],
            "low": numeric["low"][keep],
            "close": numeric["close"][keep],
            "adj_close": numeric["adj_close"][keep],
            "volume": volume[keep],
            "source": pd.Series(source, index=original.index[keep], dtype="string"),
        }
    )
    frame = (
        frame.sort_values("trade_date", kind="stable")
        .reset_index(drop=True)
        .astype({"open": "float64", "high": "float64", "low": "float64"})
    )
    frame["trade_date"] = frame["trade_date"].astype("datetime64[ns]")
    return NormalizedPrices(frame=frame, parse_errors=tuple(errors))


def _date_label(parsed_date: pd.Series, i: int) -> str | None:
    value = parsed_date.get(i)
    if value is None or pd.isna(value):
        return None
    return str(pd.Timestamp(value).date())


__all__ = [
    "PRICE_BAR_COLUMNS",
    "NormalizedPrices",
    "PriceValidationError",
    "empty_price_frame",
    "normalize_price_bars",
]
