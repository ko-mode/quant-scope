"""SPY CAPM regression + Fama-French 3-factor regression API (Phase 3B).

    GET /securities/{ticker}/factors?start&end&source

Pandas and engine orchestration live in :mod:`quantscope.services.factors`;
this handler only resolves the ticker (404 on miss), rejects an inverted date
range (422), resolves the price source, and returns the service's response.
Both models are always returned together in one response (ADR 0017 addendum,
Phase 3B) - never split across two requests.
"""

from __future__ import annotations

import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from quantscope.api.factors_schemas import FactorsResponse
from quantscope.api.schemas import PriceSource
from quantscope.config import get_settings
from quantscope.data.reference import normalize_ticker
from quantscope.db.models import Security
from quantscope.db.repositories.securities import get_security_by_ticker
from quantscope.db.session import get_session
from quantscope.services.factors import compute_ticker_factors

router = APIRouter(prefix="/securities", tags=["factors"])

SessionDep = Annotated[Session, Depends(get_session)]


def _resolve_security(session: Session, raw_ticker: str) -> Security:
    """Look up by normalised ticker; the ORM row or a 404 (no fuzzy fallback).

    Mirrors the Phase 1E securities router and ``routers.analytics``; kept
    local so this file stays self-contained.
    """
    normalized = normalize_ticker(raw_ticker)
    security = get_security_by_ticker(session, normalized) if normalized is not None else None
    if security is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"no security with ticker {raw_ticker!r}"
        )
    return security


@router.get(
    "/{ticker}/factors",
    response_model=FactorsResponse,
    summary="SPY CAPM regression + Fama-French 3-factor regression, both with Newey-West (HAC) inference",
)
def get_security_factors(
    session: SessionDep,
    ticker: Annotated[str, Path(max_length=64)],
    start: Annotated[datetime.date | None, Query(description="Inclusive ISO date.")] = None,
    end: Annotated[datetime.date | None, Query(description="Inclusive ISO date.")] = None,
    source: Annotated[
        PriceSource | None,
        Query(description="Price provider. Defaults to the configured price provider."),
    ] = None,
) -> FactorsResponse:
    security = _resolve_security(session, ticker)
    if start is not None and end is not None and start > end:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"start {start.isoformat()} is after end {end.isoformat()}",
        )
    resolved_source = source or get_settings().price_provider
    return compute_ticker_factors(
        session, security=security, source=resolved_source, start=start, end=end
    )
