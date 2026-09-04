"""Normalise and validate raw Kenneth French factor records for persistence.

Pipeline mate of :mod:`quantscope.data.prices` / :mod:`quantscope.data.validation`,
for the daily Fama/French 3 factors + RF (ADR 0009, ADR 0013):

    provider.fetch_daily_factors()  -> list[RawFactorReturn]   (percent, uninterpreted)
      -> normalize_factor_returns(...)   parse dates/numbers, drop missing-value
                                         sentinels, **convert percent -> decimal (/100)**
      -> FACTOR_RETURN_SCHEMA (Pandera)  structural checks + the abs(value) < 0.5
                                         percent-vs-decimal tripwire
      -> only rows that pass every check are eligible for the ``factor_return`` table

The ``abs(value) < 0.5`` bound is a *heuristic sanity check* for a forgotten
percent-to-decimal conversion (a real FF daily factor is within ~+/-18%). It is
deliberately **not** a database CHECK constraint: the DB owns structural
integrity, this layer owns the heuristic (ADR 0009 addendum).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pandera.pandas as pa

from quantscope.data.providers.base import RawFactorReturn
from quantscope.db.models import FACTOR_NAMES

FACTOR_RETURN_COLUMNS: tuple[str, ...] = (
    "trade_date",
    "factor_name",
    "value",
    "frequency",
    "source",
)

#: Kenneth French missing-value markers (percent units, pre-conversion).
_MISSING_SENTINELS: tuple[float, ...] = (-99.99, -999.0)
#: Percent-vs-decimal tripwire: |decimal daily factor| must stay well under this.
_DECIMAL_BOUND = 0.5


@dataclass(frozen=True, slots=True)
class FactorValidationError:
    """A structured reason a factor record is not eligible for persistence."""

    code: str
    detail: str
    factor_name: str | None = None
    trade_date: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "factor_name": self.factor_name,
            "trade_date": self.trade_date,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class NormalizedFactors:
    frame: pd.DataFrame
    parse_errors: tuple[FactorValidationError, ...] = ()


@dataclass(frozen=True, slots=True)
class FactorValidationResult:
    valid: pd.DataFrame
    errors: tuple[FactorValidationError, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def error_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for err in self.errors:
            counts[err.code] = counts.get(err.code, 0) + 1
        return counts


def empty_factor_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": pd.Series([], dtype="datetime64[ns]"),
            "factor_name": pd.Series([], dtype="string"),
            "value": pd.Series([], dtype="float64"),
            "frequency": pd.Series([], dtype="string"),
            "source": pd.Series([], dtype="string"),
        }
    )


def _raw_str(value: str | None) -> str:
    return "" if value is None else str(value).strip()


def _cell(frame: pd.DataFrame, row: int, column: str) -> str | None:
    """A frame cell as a hint string for a structured error (``None`` if empty)."""
    return str(frame.at[row, column]) or None


def normalize_factor_returns(raw: list[RawFactorReturn], *, source: str) -> NormalizedFactors:
    """Raw percent records -> canonical decimal-return frame + structured drops."""
    if not raw:
        return NormalizedFactors(frame=empty_factor_frame())

    original = pd.DataFrame(
        {
            "trade_date": [_raw_str(r.trade_date) for r in raw],
            "factor_name": [_raw_str(r.factor_name) for r in raw],
            "value": [_raw_str(r.value) for r in raw],
        }
    )
    errors: list[FactorValidationError] = []
    drop = pd.Series(False, index=original.index)

    name_norm = original["factor_name"].str.lower()
    bad_name = ~name_norm.isin(FACTOR_NAMES)
    for i in original.index[bad_name]:
        errors.append(
            FactorValidationError(
                code="unknown_factor_name",
                detail=f"unsupported factor name: {_cell(original, i, 'factor_name')!r}",
                factor_name=_cell(original, i, "factor_name"),
            )
        )
    drop |= bad_name

    parsed_date = pd.to_datetime(original["trade_date"], format="%Y%m%d", errors="coerce")
    bad_date = parsed_date.isna()
    for i in original.index[bad_date]:
        errors.append(
            FactorValidationError(
                code="invalid_trade_date",
                detail=f"unparseable trade_date: {_cell(original, i, 'trade_date')!r}",
                trade_date=_cell(original, i, "trade_date"),
            )
        )
    drop |= bad_date

    value_num = pd.to_numeric(original["value"], errors="coerce")
    missing = original["value"] == ""
    malformed = value_num.isna() & ~missing
    for i in original.index[missing]:
        errors.append(
            FactorValidationError(
                code="missing_required_value",
                detail="empty factor value",
                trade_date=_cell(original, i, "trade_date"),
            )
        )
    for i in original.index[malformed]:
        errors.append(
            FactorValidationError(
                code="malformed_numeric",
                detail=f"unparseable value: {_cell(original, i, 'value')!r}",
                trade_date=_cell(original, i, "trade_date"),
            )
        )
    drop |= missing | malformed

    sentinel = pd.Series(False, index=original.index)
    for marker in _MISSING_SENTINELS:
        sentinel |= np.isclose(value_num, marker, equal_nan=False)
    sentinel &= value_num.notna()
    for i in original.index[sentinel]:
        errors.append(
            FactorValidationError(
                code="missing_factor_value",
                detail=f"Kenneth French missing-value sentinel: {_cell(original, i, 'value')!r}",
                trade_date=_cell(original, i, "trade_date"),
            )
        )
    drop |= sentinel

    keep = ~drop
    if not keep.any():
        return NormalizedFactors(frame=empty_factor_frame(), parse_errors=tuple(errors))

    frame = pd.DataFrame(
        {
            "trade_date": parsed_date[keep].dt.normalize().to_numpy(),
            "factor_name": name_norm[keep].to_numpy(),
            # percent -> decimal daily return: 0.25% -> 0.0025
            "value": (value_num[keep] / 100.0).to_numpy(dtype="float64"),
            "frequency": "daily",
            "source": source,
        }
    ).astype({"factor_name": "string", "frequency": "string", "source": "string"})
    frame = frame.sort_values(["factor_name", "trade_date"]).reset_index(drop=True)
    return NormalizedFactors(frame=frame, parse_errors=tuple(errors))


def _all_finite(series: pd.Series) -> bool:
    return bool(np.isfinite(series.to_numpy(dtype="float64")).all())


def _unique_key(df: pd.DataFrame) -> pd.Series:
    return ~df.duplicated(subset=["trade_date", "factor_name", "source"], keep=False)


FACTOR_RETURN_SCHEMA = pa.DataFrameSchema(
    columns={
        "trade_date": pa.Column("datetime64[ns]", nullable=False),
        "factor_name": pa.Column("string", nullable=False, checks=pa.Check.isin(FACTOR_NAMES)),
        "value": pa.Column(
            "float64",
            nullable=False,
            checks=[
                pa.Check(_all_finite, name="all_finite", element_wise=False),
                pa.Check.in_range(-_DECIMAL_BOUND, _DECIMAL_BOUND),
            ],
        ),
        "frequency": pa.Column("string", nullable=False, checks=pa.Check.equal_to("daily")),
        "source": pa.Column("string", nullable=False, checks=pa.Check.str_length(min_value=1)),
    },
    checks=[pa.Check(_unique_key, name="unique_factor_key", element_wise=False)],
    strict=True,
    ordered=True,
    coerce=False,
    name="daily_factor_return",
)


def _code_for(check: str) -> str:
    if check.startswith("in_range"):
        return "value_out_of_decimal_bounds"
    if check.startswith("isin"):
        return "unknown_factor_name"
    if check.startswith("equal_to"):
        return "unexpected_frequency"
    if check.startswith("str_length"):
        return "blank_source"
    if check == "all_finite":
        return "non_finite_value"
    if check == "unique_factor_key":
        return "duplicate_factor_key"
    if "null" in check:
        return "missing_required_value"
    return "schema_violation"


def validate_factor_returns(frame: pd.DataFrame) -> FactorValidationResult:
    """Apply :data:`FACTOR_RETURN_SCHEMA`; return only rows that pass, plus reasons."""
    if list(frame.columns) != list(FACTOR_RETURN_COLUMNS):
        return FactorValidationResult(
            valid=empty_factor_frame(),
            errors=(
                FactorValidationError(
                    code="schema_violation",
                    detail=f"unexpected columns: {list(frame.columns)!r}",
                ),
            ),
        )
    if frame.empty:
        return FactorValidationResult(valid=empty_factor_frame(), errors=())

    errors: list[FactorValidationError] = []
    failing_idx: set[int] = set()
    seen: set[tuple[str, str | None, str | None]] = set()
    try:
        FACTOR_RETURN_SCHEMA.validate(frame, lazy=True)
    except pa.errors.SchemaErrors as exc:
        for case in exc.failure_cases.itertuples(index=False):
            check = str(getattr(case, "check", ""))
            row_idx = getattr(case, "index", None)
            code = _code_for(check)
            factor_name: str | None = None
            trade_date: str | None = None
            if row_idx is not None and not pd.isna(row_idx) and int(row_idx) in frame.index:
                factor_name = str(frame.at[int(row_idx), "factor_name"])
                trade_date = str(frame.at[int(row_idx), "trade_date"])[:10]  # YYYY-MM-DD hint
                failing_idx.add(int(row_idx))
            key = (code, factor_name, trade_date)
            if key in seen:
                continue
            seen.add(key)
            errors.append(
                FactorValidationError(
                    code=code,
                    detail=f"{check}: {getattr(case, 'failure_case', None)!r}",
                    factor_name=factor_name,
                    trade_date=trade_date,
                )
            )

    valid = (
        frame.drop(index=list(failing_idx)).reset_index(drop=True)
        if failing_idx
        else frame.reset_index(drop=True)
    )
    return FactorValidationResult(valid=valid, errors=tuple(errors))


def normalize_and_validate_factors(
    raw: list[RawFactorReturn], *, source: str
) -> FactorValidationResult:
    """Raw records -> normalised, validated decimal-return frame + all reasons."""
    normalized = normalize_factor_returns(raw, source=source)
    result = validate_factor_returns(normalized.frame)
    return FactorValidationResult(
        valid=result.valid,
        errors=(*normalized.parse_errors, *result.errors),
    )


__all__ = [
    "FACTOR_RETURN_COLUMNS",
    "FACTOR_RETURN_SCHEMA",
    "FactorValidationError",
    "FactorValidationResult",
    "NormalizedFactors",
    "normalize_and_validate_factors",
    "normalize_factor_returns",
    "validate_factor_returns",
]
