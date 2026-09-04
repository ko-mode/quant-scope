"""Ticker-level analytics: persisted prices -> Phase 2A engine -> wire schema.

Flow::

    price_bar rows (one source, ascending, unpaginated)
      -> adjusted-close pandas.Series          (raw `close` is never used - ADR 0012)
      -> quantscope.quant.simple_returns()     [called once, reused by every metric]
      -> return_summary / annualised_volatility / drawdown_analysis /
         historical_var_es(0.95) / historical_var_es(0.99)
      -> map each result dataclass to its Pydantic metric model
      -> assemble the ADR 0005 `assumptions` block

**Sharpe and CAPM beta are withheld in Phase 2B** (``status="unavailable"``,
``reason="risk_free_series_not_ingested"``). ADR 0017 defines both against the
Ken French daily ``RF`` series; ADR 0013 stores it in ``factor_return``; that
table and its ingestion do not exist until migration M2.
:func:`_load_daily_risk_free` is the reader seam - it returns ``None`` until M2,
and no constant/zero RF is ever substituted (ADR 0013 rejected that).

Deterministic: no clock is read. ``assumptions.as_of`` is the last return date.
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence

import pandas as pd
from sqlalchemy.orm import Session

from quantscope.api.analytics_schemas import (
    AnalyticsAssumptions,
    AnalyticsResponse,
    BetaMetric,
    DrawdownMetric,
    MetricBase,
    ReturnSummaryMetric,
    SharpeMetric,
    SuppressedMetric,
    VarEsMetric,
    VolatilityMetric,
)
from quantscope.db.models import PriceBar, Security
from quantscope.db.repositories.prices import get_all_price_bars
from quantscope.quant import (
    TRADING_DAYS_PER_YEAR,
    VAR_CONFIDENCE_LEVELS,
    DrawdownResult,
    HistoricalVarEsResult,
    InsufficientObservations,
    ReturnSummary,
    VolatilityResult,
    annualised_volatility,
    drawdown_analysis,
    historical_var_es,
    return_summary,
    simple_returns,
)
from quantscope.quant.conventions import (
    MIN_OBS_BETA,
    MIN_OBS_DRAWDOWN,
    MIN_OBS_HISTORICAL_ES,
    MIN_OBS_HISTORICAL_VAR,
    MIN_OBS_RETURN_STATS,
    MIN_OBS_SHARPE,
    MIN_OBS_VOLATILITY,
)

_RF_UNAVAILABLE_REASON = "risk_free_series_not_ingested"
_RF_SOURCE = "none_pending_fama_french_ingestion"
_VAR_ES_REQUIRED = max(MIN_OBS_HISTORICAL_VAR, MIN_OBS_HISTORICAL_ES)
_SHARPE_NOTE = (
    "sqrt(252) assumes i.i.d. daily returns; autocorrelation in daily returns "
    "biases the annualised figure. Reported, not corrected (ADR 0017)."
)
_MISSING_DATA_POLICY = (
    "one price source, never merged; analytics from adjusted close only (no raw-close "
    "fallback); metrics computed independently, so partial availability is expected"
)
_MIN_OBSERVATIONS: dict[str, int] = {
    "return_summary": MIN_OBS_RETURN_STATS,
    "volatility": MIN_OBS_VOLATILITY,
    "drawdown": MIN_OBS_DRAWDOWN,
    "sharpe": MIN_OBS_SHARPE,
    "beta": MIN_OBS_BETA,
    "var_es": _VAR_ES_REQUIRED,
}


# --------------------------------------------------------------------------- #
# Input assembly
# --------------------------------------------------------------------------- #
def _adjusted_close_series(bars: Sequence[PriceBar]) -> pd.Series:
    """PriceBar rows (ascending, single source) -> float adjusted-close Series
    indexed by ``trade_date``. Raw ``close`` is intentionally ignored (ADR 0012)."""
    index = pd.DatetimeIndex([bar.trade_date for bar in bars], name="trade_date")
    values = [float(bar.adj_close) for bar in bars]
    return pd.Series(values, index=index, dtype="float64", name="adj_close")


def _load_daily_risk_free(
    session: Session,
    *,
    start: datetime.date | None,
    end: datetime.date | None,
) -> pd.Series | None:
    """The Ken French daily ``RF`` series for the window, or ``None`` if it is not
    persisted.

    ADR 0013 keeps ``RF`` in ``factor_return`` (``factor_name = 'rf'``). That
    table and its ingestion arrive with migration M2; until then this returns
    ``None`` and the service withholds Sharpe / beta rather than substitute a
    constant rate. This function is the single seam M2 replaces.
    """
    return None


# --------------------------------------------------------------------------- #
# Result dataclass -> metric model
# --------------------------------------------------------------------------- #
def _to_date(value: pd.Timestamp | None) -> datetime.date | None:
    return None if value is None else value.date()


def _map_return_summary(
    result: ReturnSummary | InsufficientObservations,
) -> ReturnSummaryMetric:
    if isinstance(result, InsufficientObservations):
        return ReturnSummaryMetric(
            status="insufficient_observations",
            required=result.required,
            observations_used=result.observations_used,
        )
    return ReturnSummaryMetric(
        status="ok",
        observations_used=result.observations_used,
        mean_daily_return=result.mean_daily_return,
        stdev_daily_return=result.stdev_daily_return,
        cumulative_return=result.cumulative_return,
        min_daily_return=result.min_daily_return,
        max_daily_return=result.max_daily_return,
    )


def _map_volatility(
    result: VolatilityResult | InsufficientObservations,
) -> VolatilityMetric:
    if isinstance(result, InsufficientObservations):
        return VolatilityMetric(
            status="insufficient_observations",
            required=result.required,
            observations_used=result.observations_used,
        )
    return VolatilityMetric(
        status="ok",
        observations_used=result.observations_used,
        daily_volatility=result.daily_volatility,
        annualised_volatility=result.annualised_volatility,
        trading_days_per_year=result.trading_days_per_year,
    )


def _map_drawdown(result: DrawdownResult | InsufficientObservations) -> DrawdownMetric:
    if isinstance(result, InsufficientObservations):
        return DrawdownMetric(
            status="insufficient_observations",
            required=result.required,
            observations_used=result.observations_used,
        )
    return DrawdownMetric(
        status="ok",
        observations_used=result.observations_used,
        max_drawdown=result.max_drawdown,
        peak_date=_to_date(result.peak_date),
        trough_date=_to_date(result.trough_date),
        recovery_date=_to_date(result.recovery_date),
        recovered=result.recovered,
    )


def _map_var_es(
    result: HistoricalVarEsResult | InsufficientObservations,
    *,
    confidence: float,
) -> VarEsMetric:
    if isinstance(result, InsufficientObservations):
        return VarEsMetric(
            status="insufficient_observations",
            required=result.required,
            observations_used=result.observations_used,
            confidence=confidence,
        )
    return VarEsMetric(
        status="ok",
        observations_used=result.observations_used,
        confidence=result.confidence,
        var=result.var,
        expected_shortfall=result.expected_shortfall,
        threshold_return=result.threshold_return,
        tail_observations=result.tail_observations,
        horizon_days=result.horizon_days,
        method=result.method,
    )


def _sharpe_unavailable() -> SharpeMetric:
    return SharpeMetric(
        status="unavailable",
        reason=_RF_UNAVAILABLE_REASON,
        trading_days_per_year=TRADING_DAYS_PER_YEAR,
    )


def _beta_unavailable() -> BetaMetric:
    return BetaMetric(status="unavailable", reason=_RF_UNAVAILABLE_REASON)


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
def _build_assumptions(
    *,
    source: str,
    as_of: datetime.date | None,
    metrics: dict[str, MetricBase],
) -> AnalyticsAssumptions:
    suppressed = [
        SuppressedMetric(
            metric=name,
            status=metric.status,
            required=metric.required,
            observations_used=metric.observations_used,
            reason=metric.reason,
        )
        for name, metric in metrics.items()
        if metric.status != "ok"
    ]
    return AnalyticsAssumptions(
        as_of=as_of,
        annualisation_factor=TRADING_DAYS_PER_YEAR,
        data_source=source,
        missing_data_policy=_MISSING_DATA_POLICY,
        rf_source=_RF_SOURCE,
        rf=None,
        benchmark="SPY",
        market_proxy="SPY",
        var_horizon_days=1,
        confidence_levels=list(VAR_CONFIDENCE_LEVELS),
        min_observations=dict(_MIN_OBSERVATIONS),
        sharpe_annualisation_note=_SHARPE_NOTE,
        suppressed=suppressed,
    )


def compute_ticker_analytics(
    session: Session,
    *,
    security: Security,
    source: str,
    start: datetime.date | None,
    end: datetime.date | None,
) -> AnalyticsResponse:
    """Compute the analytics response for one resolved security and price source.

    Loads that source's persisted bars for the window, derives daily simple
    returns once, and runs the Phase 2A engine. Never raises for thin data: a
    security with fewer than two bars comes back with every metric suppressed and
    HTTP 200 at the router.
    """
    bars = get_all_price_bars(session, security_id=security.id, source=source, start=start, end=end)
    prices = _adjusted_close_series(bars)
    price_observations = len(prices)

    sharpe = _sharpe_unavailable()
    beta = _beta_unavailable()

    if price_observations < 2:
        # No return series can be formed: every metric is suppressed for want of
        # observations (0), and the endpoint still returns 200.
        return_summary_metric: ReturnSummaryMetric = ReturnSummaryMetric(
            status="insufficient_observations",
            required=MIN_OBS_RETURN_STATS,
            observations_used=0,
        )
        volatility_metric: VolatilityMetric = VolatilityMetric(
            status="insufficient_observations",
            required=MIN_OBS_VOLATILITY,
            observations_used=0,
        )
        drawdown_metric: DrawdownMetric = DrawdownMetric(
            status="insufficient_observations",
            required=MIN_OBS_DRAWDOWN,
            observations_used=0,
        )
        var_es_95: VarEsMetric = VarEsMetric(
            status="insufficient_observations",
            required=_VAR_ES_REQUIRED,
            observations_used=0,
            confidence=0.95,
        )
        var_es_99: VarEsMetric = VarEsMetric(
            status="insufficient_observations",
            required=_VAR_ES_REQUIRED,
            observations_used=0,
            confidence=0.99,
        )
        analytics_start: datetime.date | None = None
        analytics_end: datetime.date | None = None
        return_observations = 0
    else:
        returns = simple_returns(prices)
        return_observations = len(returns)
        analytics_start = _to_date(pd.Timestamp(returns.index[0]))
        analytics_end = _to_date(pd.Timestamp(returns.index[-1]))

        return_summary_metric = _map_return_summary(return_summary(returns))
        volatility_metric = _map_volatility(annualised_volatility(returns))
        drawdown_metric = _map_drawdown(drawdown_analysis(returns))
        var_es_95 = _map_var_es(historical_var_es(returns, 0.95), confidence=0.95)
        var_es_99 = _map_var_es(historical_var_es(returns, 0.99), confidence=0.99)

    metrics: dict[str, MetricBase] = {
        "return_summary": return_summary_metric,
        "volatility": volatility_metric,
        "sharpe": sharpe,
        "drawdown": drawdown_metric,
        "beta": beta,
        "var_es_95": var_es_95,
        "var_es_99": var_es_99,
    }
    assumptions = _build_assumptions(source=source, as_of=analytics_end, metrics=metrics)

    return AnalyticsResponse(
        ticker=security.ticker,
        source=source,
        requested_start=start,
        requested_end=end,
        price_observations=price_observations,
        return_observations=return_observations,
        analytics_start=analytics_start,
        analytics_end=analytics_end,
        return_summary=return_summary_metric,
        volatility=volatility_metric,
        sharpe=sharpe,
        drawdown=drawdown_metric,
        beta=beta,
        var_es_95=var_es_95,
        var_es_99=var_es_99,
        assumptions=assumptions,
    )


__all__ = ["compute_ticker_analytics"]
