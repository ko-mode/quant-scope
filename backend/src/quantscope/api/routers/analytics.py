"""Deterministic single-name analytics API (Phase 2B).

    GET /securities/{ticker}/analytics?start&end&source

Pandas and engine orchestration live in :mod:`quantscope.services.analytics`;
this handler only resolves the ticker (404 on miss), rejects an inverted date
range (422), resolves the price source, and returns the service's response.
One price source, never merged; analytics are computed from adjusted close.
"""

from __future__ import annotations

import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from quantscope.api.analytics_schemas import AnalyticsResponse
from quantscope.api.schemas import QuantitativeSource, resolve_quantitative_source
from quantscope.data.reference import normalize_ticker
from quantscope.db.models import Security
from quantscope.db.repositories.securities import get_security_by_ticker
from quantscope.db.session import get_session
from quantscope.services.analytics import compute_ticker_analytics

router = APIRouter(prefix="/securities", tags=["analytics"])

SessionDep = Annotated[Session, Depends(get_session)]


def _resolve_security(session: Session, raw_ticker: str) -> Security:
    """Look up by normalised ticker; the ORM row or a 404 (no fuzzy fallback).

    Mirrors the Phase 1E securities router; kept local so that file stays
    untouched by Phase 2B.
    """
    normalized = normalize_ticker(raw_ticker)
    security = get_security_by_ticker(session, normalized) if normalized is not None else None
    if security is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"no security with ticker {raw_ticker!r}"
        )
    return security


@router.get(
    "/{ticker}/analytics",
    response_model=AnalyticsResponse,
    summary="Deterministic single-name analytics from persisted adjusted-close history",
)
def get_security_analytics(
    session: SessionDep,
    ticker: Annotated[str, Path(max_length=64)],
    start: Annotated[datetime.date | None, Query(description="Inclusive ISO date.")] = None,
    end: Annotated[datetime.date | None, Query(description="Inclusive ISO date.")] = None,
    source: Annotated[
        QuantitativeSource | None,
        Query(
            description="Price provider. Defaults to the configured price provider. "
            "Stooq is excluded (QS-06), including when only the configured "
            "default provider would resolve to it (RA-02): its adjusted-close "
            "is unverified, see ADR 0022."
        ),
    ] = None,
) -> AnalyticsResponse:
    security = _resolve_security(session, ticker)
    if start is not None and end is not None and start > end:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"start {start.isoformat()} is after end {end.isoformat()}",
        )
    resolved_source = resolve_quantitative_source(source)
    return compute_ticker_analytics(
        session, security=security, source=resolved_source, start=start, end=end
    )
