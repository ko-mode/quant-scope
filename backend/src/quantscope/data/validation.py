"""Pandera validation of the canonical daily price-bar frame.

Runs after :func:`quantscope.data.prices.normalize_price_bars`. Knows nothing
about how the frame was produced. Every rejected row comes back as a structured
:class:`~quantscope.data.prices.PriceValidationError` (stable ``code``) so an
ingestion job can log it; ``valid`` contains only rows that passed every check
and are therefore eligible for persistence (Phase 1D).

V1 invariants (ADR 0006, 0012, 0021 lineage):

* ``close`` / ``adj_close`` present and ``> 0``
* ``open`` / ``high`` / ``low`` ``> 0`` when present (missing kept as NaN)
* ``volume`` ``>= 0`` when present
* ``high >= low``; ``high >= open/close``; ``low <= open/close`` when operands present
* no duplicate ``(trade_date, source)``
* ``trade_date`` is a real XNYS trading session (QS-01 / ADR 0006) - a
  weekend or holiday date is rejected the same way a non-positive price is,
  never silently persisted as a "daily" bar

A row rejected here is simply absent from ``price_bar`` - this module never
bridges a *missing* session (there is no row to reject for a date that was
never provided at all). That case is handled downstream, once returns are
computed, by :func:`quantscope.data.calendar.valid_return_adjacency_mask`,
which excludes the specific return that would otherwise span the gap.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pandera.pandas as pa

from quantscope.data.calendar import valid_session_mask
from quantscope.data.prices import (
    PRICE_BAR_COLUMNS,
    NormalizedPrices,
    PriceValidationError,
    empty_price_frame,
    normalize_price_bars,
)
from quantscope.data.providers.base import RawPriceBar


def _positive() -> pa.Check:
    # A fresh Check instance per column - pandera does not support sharing one.
    return pa.Check.gt(0)


def _valid_xnys_session() -> pa.Check:
    return pa.Check(valid_session_mask, name="valid_xnys_session", element_wise=False)


def _ohlc_bounds(df: pd.DataFrame) -> pd.Series:
    hi, lo, op, cl = df["high"], df["low"], df["open"], df["close"]
    ok = pd.Series(True, index=df.index)
    ok &= hi.isna() | lo.isna() | (hi >= lo)
    ok &= hi.isna() | (hi >= cl)
    ok &= lo.isna() | (lo <= cl)
    ok &= hi.isna() | op.isna() | (hi >= op)
    ok &= lo.isna() | op.isna() | (lo <= op)
    return ok


def _unique_trade_date_source(df: pd.DataFrame) -> pd.Series:
    return ~df.duplicated(subset=["trade_date", "source"], keep=False)


PRICE_BAR_SCHEMA = pa.DataFrameSchema(
    columns={
        "trade_date": pa.Column("datetime64[ns]", nullable=False, checks=_valid_xnys_session()),
        "open": pa.Column("float64", nullable=True, checks=_positive()),
        "high": pa.Column("float64", nullable=True, checks=_positive()),
        "low": pa.Column("float64", nullable=True, checks=_positive()),
        "close": pa.Column("float64", nullable=False, checks=_positive()),
        "adj_close": pa.Column("float64", nullable=False, checks=_positive()),
        "volume": pa.Column("Int64", nullable=True, checks=pa.Check.ge(0)),
        "source": pa.Column("string", nullable=False, checks=pa.Check.str_length(min_value=1)),
    },
    checks=[
        pa.Check(_ohlc_bounds, name="ohlc_bounds", element_wise=False),
        pa.Check(_unique_trade_date_source, name="unique_trade_date_source", element_wise=False),
    ],
    strict=True,
    ordered=True,
    coerce=False,
    name="daily_price_bar",
)


@dataclass(frozen=True, slots=True)
class PriceValidationResult:
    valid: pd.DataFrame
    errors: tuple[PriceValidationError, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def error_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for err in self.errors:
            counts[err.code] = counts.get(err.code, 0) + 1
        return counts


def _code_for(check: str, column: str | None) -> str:
    if check.startswith("greater_than_or_equal_to"):
        return "negative_volume"
    if check.startswith("greater_than"):
        return "negative_volume" if column == "volume" else "non_positive_price"
    if check.startswith("str_length"):
        return "blank_source"
    if check == "ohlc_bounds":
        return "impossible_high_low"
    if check == "unique_trade_date_source":
        return "duplicate_trade_date_source"
    if check == "valid_xnys_session":
        return "non_session_trade_date"
    if "null" in check:
        return "missing_required_value"
    return "schema_violation"


def validate_price_bars(frame: pd.DataFrame, *, source: str | None = None) -> PriceValidationResult:
    if list(frame.columns) != list(PRICE_BAR_COLUMNS):
        return PriceValidationResult(
            valid=empty_price_frame(),
            errors=(
                PriceValidationError(
                    code="schema_violation",
                    detail=f"unexpected columns: {list(frame.columns)!r}",
                ),
            ),
        )
    if frame.empty:
        return PriceValidationResult(valid=empty_price_frame(), errors=())

    # Column-scoped codes keep their column; dataframe-level structural codes
    # (a whole row is wrong) are reported once, without a column.
    _rowwise_codes = {"impossible_high_low", "duplicate_trade_date_source"}

    errors: list[PriceValidationError] = []
    failing_idx: set[int] = set()
    seen: set[tuple[str, str | None, str | None]] = set()
    try:
        PRICE_BAR_SCHEMA.validate(frame, lazy=True)
    except pa.errors.SchemaErrors as exc:
        for case in exc.failure_cases.itertuples(index=False):
            raw_column = getattr(case, "column", None)
            check = str(getattr(case, "check", ""))
            row_idx = getattr(case, "index", None)
            code = _code_for(check, raw_column)
            column = (
                None
                if code in _rowwise_codes
                else (raw_column if isinstance(raw_column, str) else None)
            )
            trade_date = None
            if row_idx is not None and not pd.isna(row_idx) and int(row_idx) in frame.index:
                cell = frame.at[int(row_idx), "trade_date"]
                trade_date = str(pd.Timestamp(cell).date())  # type: ignore[arg-type]
                failing_idx.add(int(row_idx))
            key = (code, column, trade_date)
            if key in seen:
                continue
            seen.add(key)
            if code in _rowwise_codes:
                detail = f"{check}: row fails a cross-column invariant"
            else:
                detail = f"{check}: {getattr(case, 'failure_case', None)!r}"
            errors.append(
                PriceValidationError(code=code, column=column, trade_date=trade_date, detail=detail)
            )

    valid = (
        frame.drop(index=list(failing_idx)).reset_index(drop=True)
        if failing_idx
        else frame.reset_index(drop=True)
    )
    return PriceValidationResult(valid=valid, errors=tuple(errors))


def normalize_and_validate(raw: list[RawPriceBar], *, source: str) -> PriceValidationResult:
    """Provider bars -> normalised, validated frame + all structured errors."""
    normalized: NormalizedPrices = normalize_price_bars(raw, source=source)
    result = validate_price_bars(normalized.frame, source=source)
    return PriceValidationResult(
        valid=result.valid,
        errors=(*normalized.parse_errors, *result.errors),
    )


__all__ = [
    "PRICE_BAR_SCHEMA",
    "PriceValidationResult",
    "normalize_and_validate",
    "validate_price_bars",
]
