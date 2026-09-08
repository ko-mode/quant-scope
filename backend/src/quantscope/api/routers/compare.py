"""Multi-security comparison (Phase 3A).

    GET /compare?tickers=AAPL,MSFT,NVDA&start&end&source

One common, inner-joined return panel across 2-8 securities; normalized
performance (base 100, no return divided away) and Pearson correlation, both
derived from that single panel (ADR 0017 "Multi-security comparison"). Pandas
orchestration lives in :mod:`quantscope.services.comparison`; this handler only
parses/validates the ticker list, rejects an inverted date range, resolves the
price source, and returns the service's response.
"""

from __future__ import annotations

import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from quantscope.api.comparison_schemas import ComparisonResponse
from quantscope.api.schemas import QuantitativeSource, resolve_quantitative_source
from quantscope.data.reference import normalize_ticker
from quantscope.db.session import get_session
from quantscope.services.comparison import UnknownTickerError, compute_comparison

router = APIRouter(tags=["compare"])

SessionDep = Annotated[Session, Depends(get_session)]

MIN_TICKERS = 2
MAX_TICKERS = 8


def _parse_tickers(raw: str) -> list[str]:
    """Comma-separated tickers -> normalised, de-duplicated (first-occurrence
    order preserved), 2-8 distinct tickers. A malformed ticker or the wrong
    count is a 422; an unknown-but-well-formed ticker is resolved later and
    becomes a 404 (mirrors the existing single-ticker precedent)."""
    normalized: list[str] = []
    for piece in raw.split(","):
        ticker = normalize_ticker(piece)
        if ticker is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"malformed ticker: {piece!r}"
            )
        normalized.append(ticker)
    deduped = list(dict.fromkeys(normalized))  # deterministic de-duplication
    if len(deduped) < MIN_TICKERS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"at least {MIN_TICKERS} distinct tickers are required",
        )
    if len(deduped) > MAX_TICKERS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"at most {MAX_TICKERS} tickers are supported per comparison",
        )
    return deduped


@router.get(
    "/compare",
    response_model=ComparisonResponse,
    summary="Multi-security comparison on one common aligned return panel",
)
def get_comparison(
    session: SessionDep,
    tickers: Annotated[
        str, Query(description="Comma-separated tickers, e.g. AAPL,MSFT,NVDA (2-8 distinct).")
    ],
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
) -> ComparisonResponse:
    parsed_tickers = _parse_tickers(tickers)
    if start is not None and end is not None and start > end:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"start {start.isoformat()} is after end {end.isoformat()}",
        )
    resolved_source = resolve_quantitative_source(source)
    try:
        return compute_comparison(
            session, tickers=parsed_tickers, source=resolved_source, start=start, end=end
        )
    except UnknownTickerError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
