"""Read-only securities & price-history API (Phase 1E).

    GET /securities                      search the seeded universe
    GET /securities/{ticker}             resolve one security
    GET /securities/{ticker}/prices      persisted daily bars for one source

SQL lives in ``quantscope.db.repositories``; handlers only validate inputs,
resolve the ticker, and shape the ORM rows into Pydantic models. Nothing here
writes, and nothing is created implicitly.
"""

from __future__ import annotations

import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from quantscope.api.schemas import (
    PriceBarRead,
    PriceHistoryResponse,
    PriceSource,
    SecurityListResponse,
    SecurityRead,
)
from quantscope.config import get_settings
from quantscope.data.reference import normalize_ticker
from quantscope.db.models import Security
from quantscope.db.repositories.prices import get_price_bars
from quantscope.db.repositories.securities import get_security_by_ticker, search_securities
from quantscope.db.session import get_session

router = APIRouter(prefix="/securities", tags=["securities"])

SessionDep = Annotated[Session, Depends(get_session)]

_SECURITIES_PAGE_DEFAULT = 50
_SECURITIES_PAGE_MAX = 200
_PRICES_PAGE_DEFAULT = 5_000
_PRICES_PAGE_MAX = 20_000


def _resolve_security(session: Session, raw_ticker: str) -> Security:
    """Look up by normalised ticker; return the ORM row or raise 404 (no fuzzy fallback)."""
    normalized = normalize_ticker(raw_ticker)
    security = get_security_by_ticker(session, normalized) if normalized is not None else None
    if security is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"no security with ticker {raw_ticker!r}"
        )
    return security


@router.get("", response_model=SecurityListResponse, summary="Search the security universe")
def list_securities(
    session: SessionDep,
    q: Annotated[
        str | None,
        Query(max_length=64, description="Case-insensitive partial match on ticker or name."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=_SECURITIES_PAGE_MAX)] = _SECURITIES_PAGE_DEFAULT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SecurityListResponse:
    text = q.strip() if q and q.strip() else None
    exact_ticker = normalize_ticker(text) if text is not None else None
    rows = search_securities(
        session, text=text, exact_ticker=exact_ticker, limit=limit, offset=offset
    )
    return SecurityListResponse(
        results=[SecurityRead.model_validate(row) for row in rows],
        limit=limit,
        offset=offset,
        count=len(rows),
    )


@router.get("/{ticker}", response_model=SecurityRead, summary="Resolve one security by ticker")
def get_security(
    session: SessionDep,
    ticker: Annotated[str, Path(max_length=64)],
) -> SecurityRead:
    return SecurityRead.model_validate(_resolve_security(session, ticker))


@router.get(
    "/{ticker}/prices",
    response_model=PriceHistoryResponse,
    summary="Persisted daily price bars for one security",
)
def get_security_prices(
    session: SessionDep,
    ticker: Annotated[str, Path(max_length=64)],
    start: Annotated[datetime.date | None, Query(description="Inclusive ISO date.")] = None,
    end: Annotated[datetime.date | None, Query(description="Inclusive ISO date.")] = None,
    source: Annotated[
        PriceSource | None,
        Query(description="Provider. Defaults to the configured price provider."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=_PRICES_PAGE_MAX)] = _PRICES_PAGE_DEFAULT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PriceHistoryResponse:
    security = _resolve_security(session, ticker)
    if start is not None and end is not None and start > end:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"start {start.isoformat()} is after end {end.isoformat()}",
        )

    resolved_source = source or get_settings().price_provider
    rows = get_price_bars(
        session,
        security_id=security.id,
        source=resolved_source,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )
    return PriceHistoryResponse(
        ticker=security.ticker,
        source=resolved_source,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
        count=len(rows),
        results=[PriceBarRead.model_validate(row) for row in rows],
    )
