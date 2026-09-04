"""Idempotent persistence of validated daily price bars.

``upsert_price_bars`` writes rows of the canonical, already-Pandera-validated
price frame into ``price_bar``, keyed on the composite identity
``(security_id, trade_date, source)``.

Semantics (Phase 1D):

* A row absent for that triple is inserted.
* A row present with identical values is left untouched - no write, no
  ``ingested_at`` bump.
* A row present with any differing OHLCV value is updated in place and its
  ``ingested_at`` is refreshed.
* The conflict target includes ``source``, so one provider's rows are never
  overwritten by another's - two sources for the same ``(security_id, trade_date)``
  coexist.

The database row count is therefore stable across a pure re-run.
"""

from __future__ import annotations

import datetime
import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from quantscope.db.models import PriceBar

_BATCH_SIZE = 500
#: Price columns are ``Numeric(18, 6)``; quantise to the same scale so a re-run
#: of unchanged data compares byte-identical and writes nothing.
_QUANTUM = Decimal("0.000001")
#: OHLCV columns compared to decide whether a conflicting row actually changed.
_MUTABLE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "adj_close", "volume")


@dataclass(frozen=True, slots=True)
class PriceUpsertCounts:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0

    @property
    def written(self) -> int:
        return self.inserted + self.updated

    def __add__(self, other: PriceUpsertCounts) -> PriceUpsertCounts:
        return PriceUpsertCounts(
            inserted=self.inserted + other.inserted,
            updated=self.updated + other.updated,
            unchanged=self.unchanged + other.unchanged,
        )


def _price(value: object) -> Decimal | None:
    """A canonical-frame price cell -> ``Decimal`` at scale 6, or ``None``."""
    if value is None:
        return None
    number = float(value)  # type: ignore[arg-type]
    if math.isnan(number):
        return None
    return Decimal(repr(number)).quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)


def _volume(value: object) -> int | None:
    if value is None or value is pd.NA:
        return None
    number = float(value)  # type: ignore[arg-type]
    if math.isnan(number):
        return None
    return int(number)


def _rows_from_frame(
    frame: pd.DataFrame, *, security_id: int, source: str
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for ts, open_, high, low, close, adj_close, volume in zip(
        frame["trade_date"],
        frame["open"],
        frame["high"],
        frame["low"],
        frame["close"],
        frame["adj_close"],
        frame["volume"],
        strict=True,
    ):
        trade_date: datetime.date = ts.date()  # ts is a pandas Timestamp
        rows.append(
            {
                "security_id": security_id,
                "trade_date": trade_date,
                "source": source,
                "open": _price(open_),
                "high": _price(high),
                "low": _price(low),
                "close": _price(close),
                "adj_close": _price(adj_close),
                "volume": _volume(volume),
            }
        )
    return rows


def _upsert_batch(
    session: Session, security_id: int, source: str, batch: list[dict[str, object]]
) -> PriceUpsertCounts:
    dates = [row["trade_date"] for row in batch]
    pre_existing: set[datetime.date] = set(
        session.scalars(
            select(PriceBar.trade_date).where(
                PriceBar.security_id == security_id,
                PriceBar.source == source,
                PriceBar.trade_date.in_(dates),
            )
        )
    )

    base = insert(PriceBar).values(batch)
    changed = (
        PriceBar.open.is_distinct_from(base.excluded.open)
        | PriceBar.high.is_distinct_from(base.excluded.high)
        | PriceBar.low.is_distinct_from(base.excluded.low)
        | PriceBar.close.is_distinct_from(base.excluded.close)
        | PriceBar.adj_close.is_distinct_from(base.excluded.adj_close)
        | PriceBar.volume.is_distinct_from(base.excluded.volume)
    )
    stmt = base.on_conflict_do_update(
        index_elements=["security_id", "trade_date", "source"],
        set_={col: getattr(base.excluded, col) for col in _MUTABLE_COLUMNS}
        | {"ingested_at": func.now()},
        where=changed,
    ).returning(PriceBar.trade_date)

    affected: set[datetime.date] = set(session.scalars(stmt))
    inserted = len(affected - pre_existing)
    updated = len(affected & pre_existing)
    unchanged = len(pre_existing) - updated
    return PriceUpsertCounts(inserted=inserted, updated=updated, unchanged=unchanged)


def upsert_price_bars(
    session: Session,
    *,
    security_id: int,
    source: str,
    frame: pd.DataFrame,
) -> PriceUpsertCounts:
    """Idempotently persist ``frame`` (canonical validated bars) for one security.

    ``frame`` must be the ``valid`` output of
    :func:`quantscope.data.validation.normalize_and_validate` - columns in
    canonical order, one row per ``trade_date``. ``source`` is written verbatim
    into the ``price_bar.source`` provenance column and used as the conflict key.
    """
    rows = _rows_from_frame(frame, security_id=security_id, source=source)
    total = PriceUpsertCounts()
    for start in range(0, len(rows), _BATCH_SIZE):
        batch = rows[start : start + _BATCH_SIZE]
        total = total + _upsert_batch(session, security_id, source, batch)
    return total


# --------------------------------------------------------------------------- #
# Read queries (Phase 1E API)
# --------------------------------------------------------------------------- #
def get_price_bars(
    session: Session,
    *,
    security_id: int,
    source: str,
    start: datetime.date | None,
    end: datetime.date | None,
    limit: int,
    offset: int,
) -> Sequence[PriceBar]:
    """Persisted daily bars for one security from **one** source, ``trade_date``
    ascending. A single ``source`` is always applied, so rows from different
    providers for the same ``(security_id, trade_date)`` are never merged.
    """
    stmt = select(PriceBar).where(
        PriceBar.security_id == security_id,
        PriceBar.source == source,
    )
    if start is not None:
        stmt = stmt.where(PriceBar.trade_date >= start)
    if end is not None:
        stmt = stmt.where(PriceBar.trade_date <= end)
    stmt = stmt.order_by(PriceBar.trade_date.asc()).limit(limit).offset(offset)
    return session.scalars(stmt).all()


def get_all_price_bars(
    session: Session,
    *,
    security_id: int,
    source: str,
    start: datetime.date | None,
    end: datetime.date | None,
) -> Sequence[PriceBar]:
    """Every persisted bar for one security from **one** ``source``, ``trade_date``
    ascending and unpaginated.

    Backs the Phase 2B analytics service, which needs the whole window as a
    single contiguous series. Like :func:`get_price_bars`, a single ``source`` is
    always applied, so provider series are never merged.
    """
    stmt = select(PriceBar).where(
        PriceBar.security_id == security_id,
        PriceBar.source == source,
    )
    if start is not None:
        stmt = stmt.where(PriceBar.trade_date >= start)
    if end is not None:
        stmt = stmt.where(PriceBar.trade_date <= end)
    stmt = stmt.order_by(PriceBar.trade_date.asc())
    return session.scalars(stmt).all()


__all__ = [
    "PriceUpsertCounts",
    "get_all_price_bars",
    "get_price_bars",
    "upsert_price_bars",
]
