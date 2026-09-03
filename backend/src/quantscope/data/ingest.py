"""Daily-price ingestion: fetch -> normalise -> validate -> persist, with the
run recorded in ``data_ingestion_run`` (ADR 0003).

The pipeline is a straight line and each stage is explicit:

    provider.fetch_daily_history(...)        # list[RawPriceBar]
      -> normalize_and_validate(...)         # canonical frame + structured errors
      -> upsert_price_bars(...)              # only validated rows reach the DB
      -> data_ingestion_run finalisation

The provider-independent normalisation and the Pandera schema are consumed
unchanged; invalid bars are never persisted, and every drop reason is preserved
on the returned report and in the logs.

Transaction boundary
--------------------
1. The ``data_ingestion_run`` row is committed up front with ``status='running'``
   so a crash still leaves a trace.
2. Fetch / normalise / validate happen before any ``price_bar`` write; a
   provider failure there marks the run ``failed`` and writes nothing.
3. Persistence and run finalisation share **one** transaction: the price rows
   and the accurate run row commit together, or a rollback leaves zero rows and
   a ``failed`` run. There is no state where bars are written but the run row
   misrepresents them.

One ticker == one run == one transaction (the smallest coherent target unit).
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quantscope.config import Settings
from quantscope.data.providers.base import DailyPriceProvider
from quantscope.data.providers.stooq import StooqDailyPriceProvider
from quantscope.data.providers.tiingo import TiingoDailyPriceProvider
from quantscope.data.reference import normalize_ticker
from quantscope.data.validation import normalize_and_validate
from quantscope.db.models import DataIngestionRun, Security
from quantscope.db.repositories.prices import upsert_price_bars

logger = logging.getLogger(__name__)

_ENTITY = "prices"
_ERROR_MAX = 2000


class SecurityNotFoundError(LookupError):
    """The requested ticker is not present in the seeded ``security`` universe."""

    def __init__(self, ticker: str) -> None:
        super().__init__(
            f"ticker {ticker!r} is not in the security universe; seed it first "
            f"(`quantscope seed-securities`). Ingestion never creates securities."
        )
        self.ticker = ticker


def build_price_provider(settings: Settings, name: str | None = None) -> DailyPriceProvider:
    """Construct the configured :class:`DailyPriceProvider` (default: ``price_provider``).

    Kept deliberately small - a two-line mapping, not a registry. A Tiingo
    provider with no token raises :class:`PriceProviderConfigError` here.
    """
    provider_name = (name or settings.price_provider).strip().lower()
    if provider_name == "tiingo":
        return TiingoDailyPriceProvider(
            token=settings.tiingo_api_token,
            base_url=settings.tiingo_base_url,
        )
    if provider_name == "stooq":
        return StooqDailyPriceProvider(base_url=settings.stooq_base_url)
    raise ValueError(f"unknown price provider: {provider_name!r} (expected 'tiingo' or 'stooq')")


@dataclass(frozen=True, slots=True)
class PriceIngestReport:
    run_id: int | None
    status: str
    ticker: str
    source: str
    range_start: datetime.date
    range_end: datetime.date
    fetched: int = 0
    persisted: int = 0
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
            "ticker": self.ticker,
            "source": self.source,
            "range_start": self.range_start.isoformat(),
            "range_end": self.range_end.isoformat(),
            "fetched": self.fetched,
            "persisted": self.persisted,
            "dropped": self.dropped,
            "inserted": self.inserted,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "rows_written": self.rows_written,
            "reason_counts": self.reason_counts,
        }


def _resolve_security_id(session: Session, ticker: str) -> int:
    security_id = session.scalar(select(Security.id).where(Security.ticker == ticker))
    if security_id is None:
        raise SecurityNotFoundError(ticker)
    return security_id


def run_price_ingestion(
    session: Session,
    provider: DailyPriceProvider,
    ticker: str,
    *,
    start: datetime.date,
    end: datetime.date,
    dry_run: bool = False,
) -> PriceIngestReport:
    """Ingest one ticker's daily bars for ``[start, end]`` from ``provider``."""
    normalized = normalize_ticker(ticker)
    if normalized is None:
        raise ValueError(f"malformed ticker: {ticker!r}")
    if start > end:
        raise ValueError(f"start {start.isoformat()} is after end {end.isoformat()}")

    source = provider.source_name
    logger.info(
        "price_ingestion.started",
        extra={
            "source": source,
            "ticker": normalized,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "dry_run": dry_run,
        },
    )

    if dry_run:
        bars = provider.fetch_daily_history(normalized, start=start, end=end)
        result = normalize_and_validate(bars, source=source)
        persisted = len(result.valid)
        report = PriceIngestReport(
            run_id=None,
            status="partial" if result.errors else "success",
            ticker=normalized,
            source=source,
            range_start=start,
            range_end=end,
            fetched=len(bars),
            persisted=persisted,
            dropped=len(bars) - persisted,
            reason_counts=result.error_counts,
        )
        logger.info("price_ingestion.dry_run_complete", extra=report.as_dict())
        return report

    run = DataIngestionRun(
        source=source,
        entity=_ENTITY,
        target_ref=normalized,
        range_start=start,
        range_end=end,
        status="running",
    )
    session.add(run)
    session.commit()
    run_id = run.id

    try:
        security_id = _resolve_security_id(session, normalized)
        bars = provider.fetch_daily_history(normalized, start=start, end=end)
        result = normalize_and_validate(bars, source=source)
        for err in result.errors:
            logger.warning(
                "price_ingestion.dropped_bar", extra={"ticker": normalized, **err.as_dict()}
            )

        counts = upsert_price_bars(
            session, security_id=security_id, source=source, frame=result.valid
        )
        run.rows_written = counts.written
        run.status = "partial" if result.errors else "success"
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
        logger.exception("price_ingestion.failed", extra={"run_id": run_id, "ticker": normalized})
        raise

    report = PriceIngestReport(
        run_id=run_id,
        status=run.status,
        ticker=normalized,
        source=source,
        range_start=start,
        range_end=end,
        fetched=len(bars),
        persisted=len(result.valid),
        dropped=len(bars) - len(result.valid),
        inserted=counts.inserted,
        updated=counts.updated,
        unchanged=counts.unchanged,
        rows_written=counts.written,
        reason_counts=result.error_counts,
    )
    if report.status == "partial" and report.persisted == 0:
        logger.warning("price_ingestion.all_bars_dropped", extra=report.as_dict())
    logger.info("price_ingestion.completed", extra=report.as_dict())
    return report


__all__ = [
    "PriceIngestReport",
    "SecurityNotFoundError",
    "build_price_provider",
    "run_price_ingestion",
]
