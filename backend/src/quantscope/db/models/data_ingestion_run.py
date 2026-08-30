"""``data_ingestion_run`` - one audit row per ingestion invocation.

See docs/architecture.md section 7 and ADR 0003 (ingestion is separate from the
request path; each run is recorded). Populated from Phase 1B onward; the request
path will read the latest successful run per entity to decide data freshness.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from quantscope.db.base import Base

#: Allowed values for :attr:`DataIngestionRun.entity`.
INGESTION_ENTITIES: tuple[str, ...] = ("securities", "prices", "factors", "fundamentals")
#: Allowed values for :attr:`DataIngestionRun.status`.
INGESTION_STATUSES: tuple[str, ...] = ("running", "success", "failed", "partial")


class DataIngestionRun(Base):
    __tablename__ = "data_ingestion_run"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str] = mapped_column(String(16), nullable=False)
    target_ref: Mapped[str | None] = mapped_column(String(128))
    range_start: Mapped[datetime.date | None] = mapped_column(Date)
    range_end: Mapped[datetime.date | None] = mapped_column(Date)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "entity IN ('securities', 'prices', 'factors', 'fundamentals')",
            name="entity_allowed",
        ),
        CheckConstraint(
            "status IN ('running', 'success', 'failed', 'partial')",
            name="status_allowed",
        ),
        CheckConstraint("rows_written >= 0", name="rows_written_non_negative"),
        CheckConstraint(
            "range_start IS NULL OR range_end IS NULL OR range_start <= range_end",
            name="range_start_le_end",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="finished_after_started",
        ),
        Index("ix_data_ingestion_run_entity_started_at", "entity", "started_at"),
    )
