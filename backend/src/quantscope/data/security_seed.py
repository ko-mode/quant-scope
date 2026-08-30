"""Security-universe seeding: fetch -> normalise -> de-duplicate -> upsert, with
the run recorded in ``data_ingestion_run`` (ADR 0003).

The ``data_ingestion_run`` row is committed up front with ``status='running'``
so a crash still leaves a trace; it is updated to ``success`` / ``partial`` on
completion, or ``failed`` (in its own transaction) on error.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

from sqlalchemy import func
from sqlalchemy.orm import Session

from quantscope.data.providers.base import SecurityReferenceProvider
from quantscope.data.reference import normalize_records
from quantscope.db.models import DataIngestionRun
from quantscope.db.repositories.securities import upsert_securities

logger = logging.getLogger(__name__)

_ENTITY = "securities"
_ERROR_MAX = 2000


@dataclass(frozen=True, slots=True)
class SeedReport:
    run_id: int | None
    status: str
    fetched: int = 0
    normalized: int = 0
    rejected: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    reason_counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "fetched": self.fetched,
            "normalized": self.normalized,
            "rejected": self.rejected,
            "inserted": self.inserted,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "reason_counts": self.reason_counts,
        }


def run_security_seed(
    session: Session,
    provider: SecurityReferenceProvider,
    *,
    dry_run: bool = False,
) -> SeedReport:
    logger.info("security_seed.started", extra={"source": provider.source_name, "dry_run": dry_run})

    raw = provider.fetch_securities()
    outcome = normalize_records(raw)
    logger.info(
        "security_seed.normalized",
        extra={
            "fetched": len(raw),
            "normalized": len(outcome.securities),
            "rejected": len(outcome.rejected),
            "reason_counts": outcome.reason_counts,
        },
    )
    for item in outcome.rejected:
        logger.warning(
            "security_seed.rejected",
            extra={"reason": item.reason, "raw": asdict(item.raw)},
        )

    status = "partial" if outcome.rejected else "success"

    if dry_run:
        logger.info("security_seed.dry_run_complete", extra={"status": status})
        return SeedReport(
            run_id=None,
            status=status,
            fetched=len(raw),
            normalized=len(outcome.securities),
            rejected=len(outcome.rejected),
            reason_counts=outcome.reason_counts,
        )

    run = DataIngestionRun(source=provider.source_name, entity=_ENTITY, status="running")
    session.add(run)
    session.commit()
    run_id = run.id

    try:
        counts = upsert_securities(session, outcome.securities)
        run.rows_written = counts.written
        run.status = status
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
        logger.exception("security_seed.failed", extra={"run_id": run_id})
        raise

    report = SeedReport(
        run_id=run_id,
        status=status,
        fetched=len(raw),
        normalized=len(outcome.securities),
        rejected=len(outcome.rejected),
        inserted=counts.inserted,
        updated=counts.updated,
        unchanged=counts.unchanged,
        reason_counts=outcome.reason_counts,
    )
    logger.info("security_seed.completed", extra=report.as_dict())
    return report
