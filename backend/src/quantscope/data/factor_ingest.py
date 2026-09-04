"""Daily factor ingestion: fetch -> parse -> normalise/validate -> persist, with
the run recorded in ``data_ingestion_run`` (ADR 0003, ADR 0009).

Mirrors :mod:`quantscope.data.ingest`. The Kenneth French file is not
date-filterable at the source, so it is always fetched whole; optional
``start`` / ``end`` trim the parsed frame before persistence.

Transaction boundary
--------------------
1. The ``data_ingestion_run`` row (``entity='factors'``) is committed up front
   with ``status='running'``.
2. Fetch / parse / normalise / validate happen before any ``factor_return``
   write; a provider or parse failure marks the run ``failed`` and writes nothing.
3. Persistence and run finalisation share **one** transaction.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from quantscope.config import Settings
from quantscope.data.factors import normalize_and_validate_factors
from quantscope.data.providers.base import DailyFactorProvider
from quantscope.data.providers.french_factors import KennethFrenchDailyFactorProvider
from quantscope.db.models import DataIngestionRun
from quantscope.db.repositories.factors import upsert_factor_returns

logger = logging.getLogger(__name__)

_ENTITY = "factors"
_TARGET_REF = "ff3_daily"
_ERROR_MAX = 2000


def build_factor_provider(
    settings: Settings, *, source_file: Path | None = None
) -> DailyFactorProvider:
    """Construct the Kenneth French daily factor provider (the only one in V1)."""
    return KennethFrenchDailyFactorProvider(
        url=settings.french_factors_url, source_file=source_file
    )


@dataclass(frozen=True, slots=True)
class FactorIngestReport:
    run_id: int | None
    status: str
    source: str
    range_start: datetime.date | None
    range_end: datetime.date | None
    fetched: int = 0
    normalized: int = 0
    dropped: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    rows_written: int = 0
    reason_counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "source": self.source,
            "range_start": self.range_start.isoformat() if self.range_start else None,
            "range_end": self.range_end.isoformat() if self.range_end else None,
            "fetched": self.fetched,
            "normalized": self.normalized,
            "dropped": self.dropped,
            "inserted": self.inserted,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "rows_written": self.rows_written,
            "reason_counts": self.reason_counts,
        }


def _bounds(frame: pd.DataFrame) -> tuple[datetime.date | None, datetime.date | None]:
    if frame.empty:
        return None, None
    lo = pd.Timestamp(frame["trade_date"].min()).date()
    hi = pd.Timestamp(frame["trade_date"].max()).date()
    return lo, hi


def run_factor_ingestion(
    session: Session,
    provider: DailyFactorProvider,
    *,
    start: datetime.date | None = None,
    end: datetime.date | None = None,
    dry_run: bool = False,
) -> FactorIngestReport:
    """Ingest the daily FF3 + RF dataset, optionally trimmed to ``[start, end]``."""
    if start is not None and end is not None and start > end:
        raise ValueError(f"start {start.isoformat()} is after end {end.isoformat()}")

    source = provider.source_name
    logger.info(
        "factor_ingestion.started",
        extra={"source": source, "start": str(start), "end": str(end), "dry_run": dry_run},
    )

    def _fetch_and_validate() -> tuple[int, pd.DataFrame, dict[str, int]]:
        raw = provider.fetch_daily_factors()
        result = normalize_and_validate_factors(raw, source=source)
        frame = result.valid
        if start is not None:
            frame = frame[frame["trade_date"] >= pd.Timestamp(start)]
        if end is not None:
            frame = frame[frame["trade_date"] <= pd.Timestamp(end)]
        frame = frame.reset_index(drop=True)
        return len(raw), frame, result.error_counts

    if dry_run:
        fetched, frame, reason_counts = _fetch_and_validate()
        lo, hi = _bounds(frame)
        report = FactorIngestReport(
            run_id=None,
            status="partial" if reason_counts else "success",
            source=source,
            range_start=lo,
            range_end=hi,
            fetched=fetched,
            normalized=len(frame),
            dropped=fetched - len(frame),
            reason_counts=reason_counts,
        )
        logger.info("factor_ingestion.dry_run_complete", extra=report.as_dict())
        return report

    run = DataIngestionRun(
        source=source,
        entity=_ENTITY,
        target_ref=_TARGET_REF,
        range_start=start,
        range_end=end,
        status="running",
    )
    session.add(run)
    session.commit()
    run_id = run.id

    try:
        fetched, frame, reason_counts = _fetch_and_validate()
        counts = upsert_factor_returns(session, source=source, frame=frame)
        lo, hi = _bounds(frame)
        run.rows_written = counts.written
        run.range_start = lo
        run.range_end = hi
        run.status = "partial" if reason_counts else "success"
        run.finished_at = func.now()
        session.commit()
    except Exception as exc:
        session.rollback()
        failed = session.get(DataIngestionRun, run_id)
        if failed is not None:
            failed.status = "failed"
            failed.error = repr(exc)[:_ERROR_MAX]
            failed.finished_at = func.now()
            session.commit()
        logger.exception("factor_ingestion.failed", extra={"run_id": run_id})
        raise

    report = FactorIngestReport(
        run_id=run_id,
        status=run.status,
        source=source,
        range_start=lo,
        range_end=hi,
        fetched=fetched,
        normalized=len(frame),
        dropped=fetched - len(frame),
        inserted=counts.inserted,
        updated=counts.updated,
        unchanged=counts.unchanged,
        rows_written=counts.written,
        reason_counts=reason_counts,
    )
    logger.info("factor_ingestion.completed", extra=report.as_dict())
    return report


__all__ = ["FactorIngestReport", "build_factor_provider", "run_factor_ingestion"]
