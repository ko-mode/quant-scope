"""Pandera schemas guarding the public boundary of the analytics engine.

ADR 0018 requires canonical frame shapes to be Pandera schemas validated *at the
public boundary*, not deep in the call stack. Phase 2A takes two shapes:

* an **adjusted-close price series** - float, strictly positive, finite;
* a **daily return series** - float, finite (zero variance is allowed).

Both must be indexed by a sorted, unique :class:`pandas.DatetimeIndex`. Value
constraints are expressed as Pandera :class:`~pandera.api.pandas.components.Column`
schemas; the index structure is checked explicitly so the error messages stay
precise. Any violation is re-raised as :class:`QuantInputError`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pandera.pandas as pa

from quantscope.quant.results import QuantInputError


def _all_finite(series: pd.Series) -> bool:
    return bool(np.isfinite(series.to_numpy(dtype="float64")).all())


# Note: no ``name=`` constraint - callers pass Series with varied (or absent)
# names; only dtype, nullability, finiteness and positivity are enforced here.
PRICE_SERIES_SCHEMA: pa.SeriesSchema = pa.SeriesSchema(
    float,
    nullable=False,
    coerce=True,
    checks=[
        pa.Check(_all_finite, name="all_finite", element_wise=False),
        pa.Check.gt(0, name="strictly_positive"),
    ],
)

RETURN_SERIES_SCHEMA: pa.SeriesSchema = pa.SeriesSchema(
    float,
    nullable=False,
    coerce=True,
    checks=[pa.Check(_all_finite, name="all_finite", element_wise=False)],
)


def _validate_index(series: pd.Series, *, label: str) -> None:
    index = series.index
    if not isinstance(index, pd.DatetimeIndex):
        raise QuantInputError(
            f"{label} must be indexed by a pandas.DatetimeIndex, got {type(index).__name__}"
        )
    if index.hasnans:
        raise QuantInputError(f"{label} index contains NaT")
    if not index.is_unique:
        raise QuantInputError(f"{label} index has duplicate dates")
    if not index.is_monotonic_increasing:
        raise QuantInputError(f"{label} index must be sorted ascending by date")


def _run_schema(schema: pa.SeriesSchema, series: pd.Series, *, label: str) -> pd.Series:
    try:
        validated = schema.validate(series)
    except pa.errors.SchemaError as exc:
        raise QuantInputError(f"{label} failed validation: {exc}") from exc
    return validated


def validate_price_series(prices: pd.Series, *, label: str = "price series") -> pd.Series:
    """Return ``prices`` coerced to float64, or raise :class:`QuantInputError`."""
    if len(prices) == 0:
        raise QuantInputError(f"{label} is empty")
    _validate_index(prices, label=label)
    return _run_schema(PRICE_SERIES_SCHEMA, prices, label=label)


def validate_return_series(returns: pd.Series, *, label: str = "return series") -> pd.Series:
    """Return ``returns`` coerced to float64, or raise :class:`QuantInputError`."""
    if len(returns) == 0:
        raise QuantInputError(f"{label} is empty")
    _validate_index(returns, label=label)
    return _run_schema(RETURN_SERIES_SCHEMA, returns, label=label)


__all__ = [
    "PRICE_SERIES_SCHEMA",
    "RETURN_SERIES_SCHEMA",
    "validate_price_series",
    "validate_return_series",
]
