"""Idempotent persistence of the security universe.

``upsert_securities`` matches on ``ticker`` (the ``uq_security_ticker`` unique
constraint). An existing row keeps its ``id`` and ``created_at``; only changed
columns are written, and ``updated_at`` is bumped only when something actually
changed. Rows not present in ``rows`` are left untouched - the seed never
deletes or deactivates (ADR 0021).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from quantscope.data.reference import NormalizedSecurity
from quantscope.db.models import Security

_BATCH_SIZE = 500
_MUTABLE_COLUMNS = ("name", "cik", "exchange", "asset_type")


@dataclass(frozen=True, slots=True)
class UpsertCounts:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0

    @property
    def written(self) -> int:
        return self.inserted + self.updated

    def __add__(self, other: UpsertCounts) -> UpsertCounts:
        return UpsertCounts(
            inserted=self.inserted + other.inserted,
            updated=self.updated + other.updated,
            unchanged=self.unchanged + other.unchanged,
        )


def _chunk(
    items: Sequence[NormalizedSecurity], size: int
) -> Iterable[Sequence[NormalizedSecurity]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _upsert_batch(session: Session, batch: Sequence[NormalizedSecurity]) -> UpsertCounts:
    tickers = [s.ticker for s in batch]
    pre_existing: set[str] = set(
        session.scalars(select(Security.ticker).where(Security.ticker.in_(tickers)))
    )

    base = insert(Security).values(
        [
            {
                "ticker": s.ticker,
                "name": s.name,
                "cik": s.cik,
                "exchange": s.exchange,
                "asset_type": s.asset_type,
            }
            for s in batch
        ]
    )
    changed = (
        Security.name.is_distinct_from(base.excluded.name)
        | Security.cik.is_distinct_from(base.excluded.cik)
        | Security.exchange.is_distinct_from(base.excluded.exchange)
        | Security.asset_type.is_distinct_from(base.excluded.asset_type)
    )
    stmt = base.on_conflict_do_update(
        index_elements=["ticker"],
        set_={col: getattr(base.excluded, col) for col in _MUTABLE_COLUMNS}
        | {"updated_at": func.now()},
        where=changed,
    ).returning(Security.ticker)

    affected: set[str] = set(session.scalars(stmt))
    inserted = len(affected - pre_existing)
    updated = len(affected & pre_existing)
    unchanged = len(pre_existing) - updated
    return UpsertCounts(inserted=inserted, updated=updated, unchanged=unchanged)


def upsert_securities(session: Session, rows: Sequence[NormalizedSecurity]) -> UpsertCounts:
    total = UpsertCounts()
    for batch in _chunk(rows, _BATCH_SIZE):
        total = total + _upsert_batch(session, batch)
    return total
