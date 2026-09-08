"""Multi-security comparison: persisted prices -> Phase 3A engine -> wire schema.

Flow::

    for each requested ticker (already normalised + de-duplicated by the router):
        db.repositories.securities.get_security_by_ticker      # unknown -> UnknownTickerError (router: 404)
        db.repositories.prices.get_all_price_bars(security, source, start, end)
        -> adjusted-close pandas.Series                        # raw close never read (ADR 0012)
        < 2 bars for ANY ticker -> status="unavailable" (no comparison attempted)
        else -> data.calendar.session_continuous_returns(prices)  # per ticker, before any cross-
                # asset join; the one return spanning a missing XNYS session is excluded
                # (QS-01, ADR 0006) - this is what makes each ticker's calendar actually
                # "unbroken" rather than merely assumed to be
    quant.comparison.compare_securities(returns)                # the ONE common inner-joined panel
        -> InsufficientObservations -> status="insufficient_observations"
        -> ComparisonPanel          -> status="ok"; map to NormalizedPerformance + CorrelationMatrix

One source, applied identically to every ticker; never silently substituted or
merged (ADR 0012, Phase 1E/2B precedent). No pandas logic reaches the router.
"""

from __future__ import annotations

import datetime
import math
from collections.abc import Sequence

import pandas as pd
from sqlalchemy.orm import Session

from quantscope.api.comparison_schemas import (
    ComparisonResponse,
    CorrelationMatrix,
    NormalizedPerformance,
)
from quantscope.data.calendar import session_continuous_returns
from quantscope.db.models import PriceBar, Security
from quantscope.db.repositories.prices import get_all_price_bars
from quantscope.db.repositories.securities import get_security_by_ticker
from quantscope.quant import (
    MIN_OBS_COMPARISON,
    ComparisonPanel,
    InsufficientObservations,
    compare_securities,
)

_UNAVAILABLE_REASON = "missing_price_history"


class UnknownTickerError(LookupError):
    """A requested ticker is not in the seeded security universe."""

    def __init__(self, ticker: str) -> None:
        super().__init__(f"no security with ticker {ticker!r}")
        self.ticker = ticker


def _adjusted_close_series(bars: Sequence[PriceBar]) -> pd.Series:
    """PriceBar rows (ascending, single source) -> float adjusted-close Series
    indexed by ``trade_date``. Mirrors ``services.analytics._adjusted_close_series``
    (kept local rather than shared, matching that module's own precedent)."""
    index = pd.DatetimeIndex([bar.trade_date for bar in bars], name="trade_date")
    values = [float(bar.adj_close) for bar in bars]
    return pd.Series(values, index=index, dtype="float64", name="adj_close")


def _resolve_securities(session: Session, tickers: Sequence[str]) -> dict[str, Security]:
    resolved: dict[str, Security] = {}
    for ticker in tickers:
        security = get_security_by_ticker(session, ticker)
        if security is None:
            raise UnknownTickerError(ticker)
        resolved[ticker] = security
    return resolved


def _unavailable_response(
    *,
    tickers: Sequence[str],
    source: str,
    start: datetime.date | None,
    end: datetime.date | None,
    unavailable_tickers: list[str],
) -> ComparisonResponse:
    return ComparisonResponse(
        status="unavailable",
        tickers=list(tickers),
        source=source,
        requested_start=start,
        requested_end=end,
        aligned_start=None,
        aligned_end=None,
        observations_used=None,
        required=None,
        reason=_UNAVAILABLE_REASON,
        unavailable_tickers=unavailable_tickers,
        zero_variance_tickers=None,
        normalized_performance=None,
        correlation=None,
    )


def _insufficient_response(
    *,
    tickers: Sequence[str],
    source: str,
    start: datetime.date | None,
    end: datetime.date | None,
    result: InsufficientObservations,
) -> ComparisonResponse:
    return ComparisonResponse(
        status="insufficient_observations",
        tickers=list(tickers),
        source=source,
        requested_start=start,
        requested_end=end,
        aligned_start=None,
        aligned_end=None,
        observations_used=result.observations_used,
        required=result.required,
        reason=None,
        unavailable_tickers=None,
        zero_variance_tickers=None,
        normalized_performance=None,
        correlation=None,
    )


def _ok_response(
    panel: ComparisonPanel,
    *,
    source: str,
    start: datetime.date | None,
    end: datetime.date | None,
) -> ComparisonResponse:
    norm = panel.normalized_performance
    dates: list[datetime.date | None] = [
        None if pd.isna(index_value) else pd.Timestamp(index_value).date()
        for index_value in norm.index
    ]
    series = {ticker: [float(v) for v in norm[ticker]] for ticker in panel.tickers}

    # `panel.correlation`'s rows/columns are already exactly `panel.tickers`, in
    # order (it is computed from that same column order in compare_securities),
    # so a plain array walk preserves row/column identity without a second
    # `.loc[tickers, tickers]` re-index.
    corr_values = panel.correlation.to_numpy(dtype="float64")
    matrix: list[list[float | None]] = [
        [None if math.isnan(v) else float(v) for v in row] for row in corr_values
    ]

    return ComparisonResponse(
        status="ok",
        tickers=list(panel.tickers),
        source=source,
        requested_start=start,
        requested_end=end,
        aligned_start=panel.aligned_start.date(),
        aligned_end=panel.aligned_end.date(),
        observations_used=panel.observations_used,
        required=None,
        reason=None,
        unavailable_tickers=None,
        zero_variance_tickers=list(panel.zero_variance_tickers),
        normalized_performance=NormalizedPerformance(dates=dates, series=series),
        correlation=CorrelationMatrix(tickers=list(panel.tickers), matrix=matrix),
    )


def compute_comparison(
    session: Session,
    *,
    tickers: Sequence[str],
    source: str,
    start: datetime.date | None,
    end: datetime.date | None,
) -> ComparisonResponse:
    """Compare 2+ already-normalised, already-de-duplicated tickers over one
    common aligned-return panel.

    Raises :class:`UnknownTickerError` for any ticker not in the seeded
    universe (the router maps this to 404). Never raises for thin data: fewer
    than two persisted bars for any ticker, or too little overlap, come back as
    a structured ``unavailable`` / ``insufficient_observations`` response with
    HTTP 200.
    """
    resolved = _resolve_securities(session, tickers)

    price_series: dict[str, pd.Series] = {}
    unavailable_tickers: list[str] = []
    for ticker, security in resolved.items():
        bars = get_all_price_bars(
            session, security_id=security.id, source=source, start=start, end=end
        )
        if len(bars) < 2:
            unavailable_tickers.append(ticker)
            continue
        price_series[ticker] = _adjusted_close_series(bars)

    if unavailable_tickers:
        return _unavailable_response(
            tickers=tickers,
            source=source,
            start=start,
            end=end,
            unavailable_tickers=unavailable_tickers,
        )

    returns: dict[str, pd.Series] = {}
    zero_return_tickers: list[str] = []
    for ticker, series in price_series.items():
        ticker_returns = session_continuous_returns(series)
        if len(ticker_returns) == 0:
            zero_return_tickers.append(ticker)
            continue
        returns[ticker] = ticker_returns

    if zero_return_tickers:
        # RA-03: every requested ticker has >= 2 persisted bars (checked
        # above) - price history is not missing, so "unavailable" /
        # "missing_price_history" would misrepresent this. QS-01's gap
        # suppression (data.calendar.session_continuous_returns) simply left
        # at least one ticker with zero usable one-session returns, because
        # every adjacency happened to span a missing XNYS session. Reported
        # the same way analytics.py reports the identical situation:
        # insufficient_observations, observed = 0 - never unavailable, and
        # never fed into compare_securities (its own validation raises on an
        # empty series, reserved for a genuine caller bug, not thin data).
        return _insufficient_response(
            tickers=tickers,
            source=source,
            start=start,
            end=end,
            result=InsufficientObservations("comparison", MIN_OBS_COMPARISON, 0),
        )

    result = compare_securities(returns)

    if isinstance(result, InsufficientObservations):
        return _insufficient_response(
            tickers=tickers, source=source, start=start, end=end, result=result
        )

    return _ok_response(result, source=source, start=start, end=end)


__all__ = ["UnknownTickerError", "compute_comparison"]
