"""Ticker-level analytics: persisted prices + factors -> Phase 2A engine -> wire schema.

Flow::

    price_bar rows (one source, ascending, unpaginated)
      -> adjusted-close pandas.Series          (raw `close` is never used - ADR 0012)
      -> data.calendar.session_continuous_returns()  [simple_returns(), with the
         one return spanning any missing XNYS session excluded - QS-01, ADR 0006;
         called once, reused by every metric]
      -> return_summary / annualised_volatility / drawdown_analysis /
         historical_var_es(0.95) / historical_var_es(0.99)
      -> Sharpe:  sharpe_ratio(returns, risk_free_daily = rf)
         beta:    capm_beta(returns, SPY returns, rf)
      -> map each result dataclass to its Pydantic metric model
      -> assemble the ADR 0005 `assumptions` block

The risk-free series is the **Kenneth French daily RF** persisted in
``factor_return`` (ADR 0013). :func:`_load_daily_risk_free` reads it; the quant
engine owns date alignment (asset / SPY / RF are inner-joined inside the engine).
When RF was never ingested for this source at all, Sharpe and CAPM beta report
``status="unavailable"``, ``reason="risk_free_series_not_ingested"`` - no
constant/zero RF is substituted. When RF **is** ingested but the requested
window has no overlapping rows, that is a thin window, not a missing input
(QS-03): it flows through as an empty series and Sharpe / beta report the
ordinary ``insufficient_observations`` gate instead.

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
from quantscope.config import get_settings
from quantscope.data.calendar import session_continuous_returns
from quantscope.data.reference import normalize_ticker
from quantscope.db.models import FactorReturn, PriceBar, Security
from quantscope.db.repositories.factors import existing_factor_names, get_factor_series
from quantscope.db.repositories.prices import get_all_price_bars
from quantscope.db.repositories.securities import get_security_by_ticker
from quantscope.quant import (
    TRADING_DAYS_PER_YEAR,
    VAR_CONFIDENCE_LEVELS,
    BetaResult,
    DrawdownResult,
    HistoricalVarEsResult,
    InsufficientObservations,
    ReturnSummary,
    SharpeResult,
    UndefinedResult,
    VolatilityResult,
    annualised_volatility,
    capm_beta,
    drawdown_analysis,
    historical_var_es,
    return_summary,
    sharpe_ratio,
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
_RF_SOURCE = "kenneth_french_daily"  # ADR 0013
_RF_FACTOR_NAME = "rf"
_RF_FACTOR_SOURCE = "kenneth_french"  # factor_return.source written by ingestion
_RF_BASIS = "daily_series"
_BETA_NO_BENCHMARK_SECURITY = "benchmark_security_not_found"
_BETA_NO_BENCHMARK_HISTORY = "benchmark_price_history_unavailable"

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


def _risk_free_series(rows: Sequence[FactorReturn]) -> pd.Series:
    index = pd.DatetimeIndex([row.trade_date for row in rows], name="trade_date")
    values = [float(row.value) for row in rows]
    return pd.Series(values, index=index, dtype="float64", name="rf")


def _load_daily_risk_free(
    session: Session,
    *,
    start: datetime.date | None,
    end: datetime.date | None,
) -> pd.Series | None:
    """The Kenneth French daily ``RF`` series for ``[start, end]``.

    Reads ``factor_return`` rows with ``factor_name = 'rf'`` from the
    ``kenneth_french`` source (ADR 0013). Three cases (QS-03):

    * rows exist in the window -> that series.
    * no rows in the window, but ``rf`` is ingested for this source at some
      other date -> an **empty** (not ``None``) series. The quant engine's own
      inner join then sees zero aligned observations, so Sharpe / beta report
      ``insufficient_observations`` - a thin window, not a missing input.
    * ``rf`` was never ingested for this source at all -> ``None``. The
      service then reports ``unavailable`` rather than substitute a constant
      rate.

    Returning an empty series (not raising, not ``None``) for the middle case
    is what lets a genuinely-ingested-but-out-of-range RF series flow through
    the same ``insufficient_observations`` gate as any other thin window,
    instead of being misreported as "not ingested".
    """
    rows = get_factor_series(
        session,
        factor_name=_RF_FACTOR_NAME,
        source=_RF_FACTOR_SOURCE,
        start=start,
        end=end,
    )
    if rows:
        return _risk_free_series(rows)
    if _RF_FACTOR_NAME in existing_factor_names(
        session, source=_RF_FACTOR_SOURCE, factor_names=(_RF_FACTOR_NAME,)
    ):
        return _risk_free_series(())
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


def _map_sharpe(
    result: SharpeResult | InsufficientObservations | UndefinedResult,
) -> SharpeMetric:
    if isinstance(result, InsufficientObservations):
        return SharpeMetric(
            status="insufficient_observations",
            required=result.required,
            observations_used=result.observations_used,
            trading_days_per_year=TRADING_DAYS_PER_YEAR,
        )
    if isinstance(result, UndefinedResult):
        return SharpeMetric(
            status="undefined",
            reason=result.reason,
            observations_used=result.observations_used,
            trading_days_per_year=TRADING_DAYS_PER_YEAR,
        )
    return SharpeMetric(
        status="ok",
        observations_used=result.observations_used,
        sharpe_ratio=result.sharpe_ratio,
        mean_daily_excess_return=result.mean_daily_excess_return,
        daily_excess_volatility=result.daily_excess_volatility,
        trading_days_per_year=result.trading_days_per_year,
        risk_free_basis=result.risk_free_basis,
    )


def _map_beta(
    result: BetaResult | InsufficientObservations | UndefinedResult,
) -> BetaMetric:
    if isinstance(result, InsufficientObservations):
        return BetaMetric(
            status="insufficient_observations",
            required=result.required,
            observations_used=result.observations_used,
        )
    if isinstance(result, UndefinedResult):
        return BetaMetric(
            status="undefined",
            reason=result.reason,
            observations_used=result.observations_used,
        )
    return BetaMetric(
        status="ok",
        observations_used=result.observations_used,
        beta=result.beta,
        alpha_daily=result.alpha_daily,
        r_squared=result.r_squared,
        aligned_start=_to_date(result.aligned_start),
        aligned_end=_to_date(result.aligned_end),
    )


# --------------------------------------------------------------------------- #
# Sharpe / beta orchestration
# --------------------------------------------------------------------------- #
def _compute_sharpe(returns: pd.Series, rf: pd.Series | None) -> SharpeMetric:
    if rf is None:
        return SharpeMetric(
            status="unavailable",
            reason=_RF_UNAVAILABLE_REASON,
            trading_days_per_year=TRADING_DAYS_PER_YEAR,
        )
    if len(rf) == 0:
        # rf is ingested for this source, just not covering this window
        # (QS-03) - zero aligned observations, not a structural error; never
        # feed an empty series into sharpe_ratio (its own validation raises
        # on that, reserved for a genuine caller bug, not a thin window).
        return SharpeMetric(
            status="insufficient_observations",
            required=MIN_OBS_SHARPE,
            observations_used=0,
            trading_days_per_year=TRADING_DAYS_PER_YEAR,
        )
    return _map_sharpe(sharpe_ratio(returns, risk_free_daily=rf))


def _compute_beta(
    session: Session,
    *,
    asset_returns: pd.Series,
    source: str,
    start: datetime.date | None,
    end: datetime.date | None,
    rf: pd.Series | None,
) -> BetaMetric:
    if rf is None:
        return BetaMetric(status="unavailable", reason=_RF_UNAVAILABLE_REASON)
    if len(rf) == 0:
        return BetaMetric(
            status="insufficient_observations", required=MIN_OBS_BETA, observations_used=0
        )

    benchmark = normalize_ticker(get_settings().default_benchmark_ticker)
    spy = get_security_by_ticker(session, benchmark) if benchmark is not None else None
    if spy is None:
        return BetaMetric(status="unavailable", reason=_BETA_NO_BENCHMARK_SECURITY)

    spy_bars = get_all_price_bars(session, security_id=spy.id, source=source, start=start, end=end)
    if len(spy_bars) < 2:
        return BetaMetric(status="unavailable", reason=_BETA_NO_BENCHMARK_HISTORY)

    spy_returns = session_continuous_returns(_adjusted_close_series(spy_bars))
    if len(spy_returns) == 0:
        # SPY-01: >= 2 SPY bars are already confirmed above - SPY's price
        # history is not missing, so `unavailable` would misrepresent this.
        # Every adjacency simply happened to span a missing XNYS session
        # (QS-01), leaving zero usable benchmark returns. Reported the same
        # way a thin RF series is reported just above: insufficient
        # observations, observed = 0, against the same beta gate.
        return BetaMetric(
            status="insufficient_observations", required=MIN_OBS_BETA, observations_used=0
        )
    return _map_beta(capm_beta(asset_returns, spy_returns, rf))


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
def _build_assumptions(
    *,
    source: str,
    as_of: datetime.date | None,
    rf_available: bool,
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
        rf_source=_RF_SOURCE if rf_available else "not_ingested",
        rf=None,
        rf_basis=_RF_BASIS if rf_available else None,
        benchmark=get_settings().default_benchmark_ticker,
        market_proxy=get_settings().default_benchmark_ticker,
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
    returns once, runs the Phase 2A engine, and adds Sharpe / CAPM beta against
    the persisted Kenneth French daily RF series. Never raises for thin data.
    """
    bars = get_all_price_bars(session, security_id=security.id, source=source, start=start, end=end)
    prices = _adjusted_close_series(bars)
    price_observations = len(prices)
    rf = _load_daily_risk_free(session, start=start, end=end)

    # QS-01: even with >= 2 prices, every adjacency can happen to span a
    # missing XNYS session, leaving zero usable returns - the same
    # "insufficient" outcome as too few prices, computed once here so neither
    # branch below ever calls a metric function with an empty return series
    # (validate_return_series treats that as a structural error, not a thin
    # one - reserved for a genuine caller bug).
    returns = session_continuous_returns(prices) if price_observations >= 2 else prices.iloc[0:0]
    return_observations = len(returns)

    if return_observations == 0:
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
        sharpe_metric: SharpeMetric = SharpeMetric(
            status="insufficient_observations",
            required=MIN_OBS_SHARPE,
            observations_used=0,
            trading_days_per_year=TRADING_DAYS_PER_YEAR,
        )
        beta_metric: BetaMetric = BetaMetric(
            status="insufficient_observations",
            required=MIN_OBS_BETA,
            observations_used=0,
        )
        analytics_start: datetime.date | None = None
        analytics_end: datetime.date | None = None
    else:
        analytics_start = _to_date(pd.Timestamp(returns.index[0]))
        analytics_end = _to_date(pd.Timestamp(returns.index[-1]))

        return_summary_metric = _map_return_summary(return_summary(returns))
        volatility_metric = _map_volatility(annualised_volatility(returns))
        # anchor_date = the price immediately preceding the first *surviving*
        # return (not necessarily prices.index[0] - QS-01's gap filtering can
        # exclude the very first adjacency), so a drawdown starting on that
        # first return reports its truthful pre-return peak date (QS-02).
        anchor_pos = prices.index.get_indexer(pd.DatetimeIndex([returns.index[0]]))[0] - 1
        drawdown_metric = _map_drawdown(
            drawdown_analysis(returns, anchor_date=pd.Timestamp(prices.index[anchor_pos]))
        )
        var_es_95 = _map_var_es(historical_var_es(returns, 0.95), confidence=0.95)
        var_es_99 = _map_var_es(historical_var_es(returns, 0.99), confidence=0.99)
        sharpe_metric = _compute_sharpe(returns, rf)
        beta_metric = _compute_beta(
            session, asset_returns=returns, source=source, start=start, end=end, rf=rf
        )

    metrics: dict[str, MetricBase] = {
        "return_summary": return_summary_metric,
        "volatility": volatility_metric,
        "sharpe": sharpe_metric,
        "drawdown": drawdown_metric,
        "beta": beta_metric,
        "var_es_95": var_es_95,
        "var_es_99": var_es_99,
    }
    assumptions = _build_assumptions(
        source=source, as_of=analytics_end, rf_available=rf is not None, metrics=metrics
    )

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
        sharpe=sharpe_metric,
        drawdown=drawdown_metric,
        beta=beta_metric,
        var_es_95=var_es_95,
        var_es_99=var_es_99,
        assumptions=assumptions,
    )


__all__ = ["compute_ticker_analytics"]
