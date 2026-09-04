"""Idempotent persistence and reads for daily factor returns (``factor_return``).

Mirrors :mod:`quantscope.db.repositories.prices`:

* ``upsert_factor_returns`` writes rows of the Pandera-validated factor frame,
  keyed on ``(factor_name, frequency, trade_date, source)``. A row absent is
  inserted; a row present with the same ``value`` is left untouched (no write,
  ``ingested_at`` preserved); a row whose ``value`` differs is updated in place
  and ``ingested_at`` refreshed. The row count is stable across a pure re-run.
* Reads return ORM rows in ascending date order for one ``source`` only, so
  factor series from different sources are never merged. No pandas or statistics
  here - the service layer builds the ``pandas.Series``.
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

import pandas as pd
from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from quantscope.db.models import FACTOR_NAMES, FactorReturn

_BATCH_SIZE = 1000
_FREQUENCY = "daily"
#: ``value`` is ``Numeric(18, 6)``; quantise so an unchanged re-run compares equal.
_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class FactorUpsertCounts:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0

    @property
    def written(self) -> int:
        return self.inserted + self.updated

    def __add__(self, other: FactorUpsertCounts) -> FactorUpsertCounts:
        return FactorUpsertCounts(
            inserted=self.inserted + other.inserted,
            updated=self.updated + other.updated,
            unchanged=self.unchanged + other.unchanged,
        )


def _value(raw: object) -> Decimal:
    return Decimal(repr(float(raw))).quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)  # type: ignore[arg-type]


def _rows_from_frame(frame: pd.DataFrame, *, source: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for ts, factor_name, value in zip(
        frame["trade_date"], frame["factor_name"], frame["value"], strict=True
    ):
        trade_date: datetime.date = pd.Timestamp(ts).date()
        rows.append(
            {
                "factor_name": str(factor_name),
                "frequency": _FREQUENCY,
                "trade_date": trade_date,
                "source": source,
                "value": _value(value),
            }
        )
    return rows


def _upsert_batch(
    session: Session, source: str, batch: list[dict[str, object]]
) -> FactorUpsertCounts:
    keys = [(row["factor_name"], row["trade_date"]) for row in batch]
    pre_existing: set[tuple[str, datetime.date]] = {
        (row.factor_name, row.trade_date)
        for row in session.execute(
            select(FactorReturn.factor_name, FactorReturn.trade_date).where(
                FactorReturn.source == source,
                FactorReturn.frequency == _FREQUENCY,
                tuple_(FactorReturn.factor_name, FactorReturn.trade_date).in_(keys),
            )
        ).all()
    }

    base = insert(FactorReturn).values(batch)
    stmt = base.on_conflict_do_update(
        index_elements=["factor_name", "frequency", "trade_date", "source"],
        set_={"value": base.excluded.value, "ingested_at": func.now()},
        where=FactorReturn.value.is_distinct_from(base.excluded.value),
    ).returning(FactorReturn.factor_name, FactorReturn.trade_date)
    affected: set[tuple[str, datetime.date]] = {
        (row.factor_name, row.trade_date) for row in session.execute(stmt).all()
    }
    inserted = len(affected - pre_existing)
    updated = len(affected & pre_existing)
    unchanged = len(pre_existing) - updated
    return FactorUpsertCounts(inserted=inserted, updated=updated, unchanged=unchanged)


def upsert_factor_returns(
    session: Session, *, source: str, frame: pd.DataFrame
) -> FactorUpsertCounts:
    """Idempotently persist ``frame`` (validated factor rows) for one ``source``.

    ``frame`` must be the ``valid`` output of
    :func:`quantscope.data.factors.normalize_and_validate_factors` - columns
    ``(trade_date, factor_name, value, frequency, source)``, ``value`` a decimal
    daily return.
    """
    rows = _rows_from_frame(frame, source=source)
    total = FactorUpsertCounts()
    for start in range(0, len(rows), _BATCH_SIZE):
        total = total + _upsert_batch(session, source, rows[start : start + _BATCH_SIZE])
    return total


def get_factor_series(
    session: Session,
    *,
    factor_name: str,
    source: str,
    start: datetime.date | None,
    end: datetime.date | None,
) -> Sequence[FactorReturn]:
    """One factor's daily series from **one** source, ``trade_date`` ascending."""
    stmt = select(FactorReturn).where(
        FactorReturn.factor_name == factor_name,
        FactorReturn.source == source,
        FactorReturn.frequency == _FREQUENCY,
    )
    if start is not None:
        stmt = stmt.where(FactorReturn.trade_date >= start)
    if end is not None:
        stmt = stmt.where(FactorReturn.trade_date <= end)
    return session.scalars(stmt.order_by(FactorReturn.trade_date.asc())).all()


def get_factor_panel(
    session: Session,
    *,
    source: str,
    start: datetime.date | None,
    end: datetime.date | None,
    factor_names: Sequence[str] = FACTOR_NAMES,
) -> Sequence[FactorReturn]:
    """All requested factors from one source, ordered ``(trade_date, factor_name)``.

    Provided for Phase 3B FF3 regression reuse; Phase 2B.1 only reads ``rf`` via
    :func:`get_factor_series`.
    """
    stmt = select(FactorReturn).where(
        FactorReturn.source == source,
        FactorReturn.frequency == _FREQUENCY,
        FactorReturn.factor_name.in_(list(factor_names)),
    )
    if start is not None:
        stmt = stmt.where(FactorReturn.trade_date >= start)
    if end is not None:
        stmt = stmt.where(FactorReturn.trade_date <= end)
    return session.scalars(
        stmt.order_by(FactorReturn.trade_date.asc(), FactorReturn.factor_name.asc())
    ).all()


__all__ = [
    "FactorUpsertCounts",
    "get_factor_panel",
    "get_factor_series",
    "upsert_factor_returns",
]
