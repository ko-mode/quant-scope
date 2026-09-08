"""Ticker-level factor regressions: persisted prices + factors -> Phase 3B
engine -> wire schema.

Flow::

    price_bar rows (one source, ascending, unpaginated)
      -> adjusted-close pandas.Series          (raw `close` is never used - ADR 0012)
      -> data.calendar.session_continuous_returns()  [simple_returns(), with the one
         return spanning any missing XNYS session excluded - QS-01, ADR 0006; called
         once, reused by both models]
      -> RF:      the persisted Kenneth French daily `rf` series (ADR 0013)
      -> CAPM:    SPY adjusted-close -> session_continuous_returns -> quant.capm_regression
      -> FF3:     Mkt-RF / SMB / HML from `factor_return` -> quant.ff3_regression
      -> map each result to FactorModelResult (`ok` / `insufficient_observations` /
         `undefined` / `unavailable`)
      -> assemble the ADR 0005 `assumptions` block (with the mandatory SPY-vs-Mkt-RF note)

CAPM and FF3 are independent: RF is required by both (missing RF makes both
`unavailable`), but a missing SPY benchmark only affects CAPM, and missing
factor history only affects FF3. Never raises for thin data - the endpoint
always returns 200 with each model's status carrying the explanation.

This does not touch :mod:`quantscope.quant.risk` or
:mod:`quantscope.services.analytics` - the existing SPY CAPM beta ("Beta vs
SPY") is unaffected by this module; the SPY-resolution logic here is a
deliberate, small duplicate of ``services.analytics._compute_beta`` (mirrors
that module's own precedent for ``_adjusted_close_series``: identical helpers
are kept local to each service rather than shared, since sharing a
seven-line helper is not worth a new module boundary).
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from typing import Final

import pandas as pd
from sqlalchemy.orm import Session

from quantscope.api.factors_schemas import (
    FactorModelResult,
    FactorsAssumptions,
    FactorsResponse,
    RegressionCoefficientSchema,
)
from quantscope.config import get_settings
from quantscope.data.calendar import session_continuous_returns
from quantscope.data.reference import normalize_ticker
from quantscope.db.models import FactorReturn, PriceBar, Security
from quantscope.db.repositories.factors import (
    existing_factor_names,
    get_factor_panel,
    get_factor_series,
)
from quantscope.db.repositories.prices import get_all_price_bars
from quantscope.db.repositories.securities import get_security_by_ticker
from quantscope.quant import (
    FactorRegressionResult,
    InsufficientObservations,
    UndefinedResult,
    capm_regression,
    ff3_regression,
)
from quantscope.quant.conventions import MIN_OBS_CAPM_REGRESSION, MIN_OBS_FF3_REGRESSION

_FACTOR_SOURCE = "kenneth_french"  # factor_return.source written by ingestion (ADR 0009)
_RF_SOURCE_LABEL = "kenneth_french_daily"  # ADR 0013, matches services.analytics
_RF_FACTOR_NAME = "rf"
_FF3_FACTOR_NAMES: Final[tuple[str, ...]] = ("mkt_rf", "smb", "hml")

_RF_UNAVAILABLE_REASON = "risk_free_series_not_ingested"
_PRICE_UNAVAILABLE_REASON = "asset_price_history_unavailable"
_BETA_NO_BENCHMARK_SECURITY = "benchmark_security_not_found"
_BETA_NO_BENCHMARK_HISTORY = "benchmark_price_history_unavailable"

_CAPM_VS_FF3_NOTE = (
    "The SPY CAPM beta (Risk & Return tab) and the FF3 Mkt-RF coefficient below are "
    "different quantities: SPY is one S&P 500 ETF; Mkt-RF is the excess return of the "
    "broad cap-weighted US market. Both are computed here, labelled distinctly; neither "
    'is "the" beta (ADR 0005, ADR 0009, ADR 0017).'
)
_ALPHA_NOTE = "Alpha is the daily regression intercept. It is not annualized."
_HAC_LAG_RULE = "floor(4 * (observations_used / 100) ** (2/9)), minimum 1 (Newey & West, 1994)"
_MIN_OBSERVATIONS: dict[str, int] = {
    "capm_regression": MIN_OBS_CAPM_REGRESSION,
    "ff3_regression": MIN_OBS_FF3_REGRESSION,
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


def _factor_series(rows: Sequence[FactorReturn], name: str) -> pd.Series:
    index = pd.DatetimeIndex([row.trade_date for row in rows], name="trade_date")
    values = [float(row.value) for row in rows]
    return pd.Series(values, index=index, dtype="float64", name=name)


def _load_daily_risk_free(
    session: Session, *, start: datetime.date | None, end: datetime.date | None
) -> pd.Series | None:
    """The Kenneth French daily ``RF`` series for ``[start, end]``.

    Mirrors ``services.analytics._load_daily_risk_free``'s three-case
    distinction (QS-03): rows in the window -> that series; ``rf`` ingested
    for this source at some other date but not in this window -> an *empty*
    (not ``None``) series, so the quant layer's own gate reports
    ``insufficient_observations`` rather than "not ingested"; ``rf`` never
    ingested for this source at all -> ``None``.
    """
    rows = get_factor_series(
        session, factor_name=_RF_FACTOR_NAME, source=_FACTOR_SOURCE, start=start, end=end
    )
    if rows:
        return _factor_series(rows, _RF_FACTOR_NAME)
    if _RF_FACTOR_NAME in existing_factor_names(
        session, source=_FACTOR_SOURCE, factor_names=(_RF_FACTOR_NAME,)
    ):
        return _factor_series((), _RF_FACTOR_NAME)
    return None


def _load_ff3_factor_panel(
    session: Session, *, start: datetime.date | None, end: datetime.date | None
) -> dict[str, pd.Series]:
    """``{mkt_rf, smb, hml}`` -> Series, one query, one source (ADR 0009).

    Always returns all three names as keys - a factor absent from the
    requested window but ingested globally maps to an *empty* Series, not an
    absent key (QS-03), so it flows through to the quant layer's own
    ``insufficient_observations`` gate instead of being mistaken for "never
    ingested". Use :func:`_globally_missing_ff3_factors` to detect genuine
    absence.
    """
    rows = get_factor_panel(
        session, source=_FACTOR_SOURCE, start=start, end=end, factor_names=_FF3_FACTOR_NAMES
    )
    grouped: dict[str, list[FactorReturn]] = {name: [] for name in _FF3_FACTOR_NAMES}
    for row in rows:
        grouped[row.factor_name].append(row)
    return {name: _factor_series(rows_, name) for name, rows_ in grouped.items()}


def _globally_missing_ff3_factors(session: Session) -> list[str]:
    """Which of ``mkt_rf`` / ``smb`` / ``hml`` were never ingested for this
    source at all, irrespective of any requested window (QS-03)."""
    existing = existing_factor_names(session, source=_FACTOR_SOURCE, factor_names=_FF3_FACTOR_NAMES)
    return [name for name in _FF3_FACTOR_NAMES if name not in existing]


def _resolve_spy_returns(
    session: Session, *, source: str, start: datetime.date | None, end: datetime.date | None
) -> pd.Series | FactorModelResult:
    """SPY's daily simple returns for the window, or the already-built failure
    ``FactorModelResult`` for the CAPM model (``unavailable`` or
    ``insufficient_observations``).

    Mirrors ``services.analytics._compute_beta``'s benchmark resolution
    exactly (same settings key, same three-way outcome - SPY-01) - kept local
    rather than shared, matching that module's own precedent.
    """
    benchmark = normalize_ticker(get_settings().default_benchmark_ticker)
    spy = get_security_by_ticker(session, benchmark) if benchmark is not None else None
    if spy is None:
        return _unavailable(_BETA_NO_BENCHMARK_SECURITY)
    spy_bars = get_all_price_bars(session, security_id=spy.id, source=source, start=start, end=end)
    if len(spy_bars) < 2:
        return _unavailable(_BETA_NO_BENCHMARK_HISTORY)
    returns = session_continuous_returns(_adjusted_close_series(spy_bars))
    if len(returns) == 0:
        # SPY-01: >= 2 SPY bars are already confirmed above - SPY's price
        # history is not missing, so `unavailable` would misrepresent this.
        # Every adjacency simply happened to span a missing XNYS session
        # (QS-01), leaving zero usable benchmark returns.
        return _insufficient(MIN_OBS_CAPM_REGRESSION)
    return returns


# --------------------------------------------------------------------------- #
# Result dataclass -> wire schema
# --------------------------------------------------------------------------- #
def _unavailable(reason: str) -> FactorModelResult:
    return FactorModelResult(status="unavailable", reason=reason)


def _insufficient(required: int) -> FactorModelResult:
    """A model whose required input series exists but is empty - zero usable
    aligned observations by construction. The quant layer's own validation
    (``validate_return_series``) treats a literally empty series as a
    structural error, not a thin one, so this is constructed directly rather
    than ever calling ``capm_regression`` / ``ff3_regression`` with one."""
    return FactorModelResult(
        status="insufficient_observations", required=required, observations_used=0
    )


def _map_regression_result(
    result: FactorRegressionResult | InsufficientObservations | UndefinedResult,
) -> FactorModelResult:
    if isinstance(result, InsufficientObservations):
        return FactorModelResult(
            status="insufficient_observations",
            required=result.required,
            observations_used=result.observations_used,
        )
    if isinstance(result, UndefinedResult):
        return FactorModelResult(
            status="undefined",
            reason=result.reason,
            observations_used=result.observations_used,
        )
    return FactorModelResult(
        status="ok",
        observations_used=result.observations_used,
        aligned_start=result.aligned_start.date(),
        aligned_end=result.aligned_end.date(),
        coefficients=[
            RegressionCoefficientSchema(
                name=c.name,
                estimate=c.estimate,
                std_error=c.std_error,
                t_stat=c.t_stat,
                p_value=c.p_value,
                ci_low=c.ci_low,
                ci_high=c.ci_high,
            )
            for c in result.coefficients
        ],
        r_squared=result.r_squared,
        adjusted_r_squared=result.adjusted_r_squared,
        hac_lags=result.hac_lags,
    )


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
def _build_assumptions(*, rf_available: bool) -> FactorsAssumptions:
    return FactorsAssumptions(
        capm_vs_ff3_note=_CAPM_VS_FF3_NOTE,
        alpha_note=_ALPHA_NOTE,
        factor_source=_FACTOR_SOURCE,
        rf_source=_RF_SOURCE_LABEL if rf_available else "not_ingested",
        hac_lag_rule=_HAC_LAG_RULE,
        min_observations=dict(_MIN_OBSERVATIONS),
    )


def compute_ticker_factors(
    session: Session,
    *,
    security: Security,
    source: str,
    start: datetime.date | None,
    end: datetime.date | None,
) -> FactorsResponse:
    """Compute the CAPM (SPY) and FF3 factor regressions for one resolved
    security and price source. Never raises for thin data; the endpoint
    always returns 200 with each model's own status.
    """
    bars = get_all_price_bars(session, security_id=security.id, source=source, start=start, end=end)
    prices = _adjusted_close_series(bars)
    # RF is checked unconditionally, before branching on price-history length
    # (QS-03) - matching services.analytics's order - so assumptions.rf_source
    # is never reported as "not_ingested" merely because the *asset's* price
    # history happened to be thin; RF's own availability is a separate fact.
    rf = _load_daily_risk_free(session, start=start, end=end)

    if len(prices) < 2:
        capm = _unavailable(_PRICE_UNAVAILABLE_REASON)
        ff3 = _unavailable(_PRICE_UNAVAILABLE_REASON)
        return FactorsResponse(
            ticker=security.ticker,
            source=source,
            requested_start=start,
            requested_end=end,
            capm=capm,
            ff3=ff3,
            assumptions=_build_assumptions(rf_available=rf is not None),
        )

    if rf is None:
        capm = _unavailable(_RF_UNAVAILABLE_REASON)
        ff3 = _unavailable(_RF_UNAVAILABLE_REASON)
        return FactorsResponse(
            ticker=security.ticker,
            source=source,
            requested_start=start,
            requested_end=end,
            capm=capm,
            ff3=ff3,
            assumptions=_build_assumptions(rf_available=False),
        )

    asset_returns = session_continuous_returns(prices)

    # Both empty-series edge cases below are constructed directly rather than
    # ever calling capm_regression / ff3_regression: the quant layer's own
    # validation treats a literally empty series as a structural error (raise),
    # not a thin one - these are the two ways QS-01 (all adjacencies gapped)
    # and QS-03 (rf ingested, but not covering this window) can legitimately
    # produce one. Zero observations is still zero observations - insufficient,
    # not a crash.
    if len(asset_returns) == 0:
        # RA-03: >= 2 persisted bars were already confirmed above - price
        # history is not missing, so `unavailable` / a "price history
        # unavailable" reason would misrepresent this. Every adjacency simply
        # happened to span a missing XNYS session (QS-01), leaving zero usable
        # returns. Reported the same way `services.analytics` reports the
        # identical situation for its own return series:
        # insufficient_observations, observed = 0 - consistent across
        # analytics/comparison/factors.
        capm = _insufficient(MIN_OBS_CAPM_REGRESSION)
        ff3 = _insufficient(MIN_OBS_FF3_REGRESSION)
        return FactorsResponse(
            ticker=security.ticker,
            source=source,
            requested_start=start,
            requested_end=end,
            capm=capm,
            ff3=ff3,
            assumptions=_build_assumptions(rf_available=True),
        )

    if len(rf) == 0:
        capm = _insufficient(MIN_OBS_CAPM_REGRESSION)
        ff3 = _insufficient(MIN_OBS_FF3_REGRESSION)
        return FactorsResponse(
            ticker=security.ticker,
            source=source,
            requested_start=start,
            requested_end=end,
            capm=capm,
            ff3=ff3,
            assumptions=_build_assumptions(rf_available=True),
        )

    spy_result = _resolve_spy_returns(session, source=source, start=start, end=end)
    if isinstance(spy_result, FactorModelResult):
        capm = spy_result
    else:
        capm = _map_regression_result(capm_regression(asset_returns, spy_result, rf))

    factors = _load_ff3_factor_panel(session, start=start, end=end)
    missing = _globally_missing_ff3_factors(session)
    if missing:
        ff3 = _unavailable(f"factor_not_ingested:{missing[0]}")
    elif any(len(factors[name]) == 0 for name in _FF3_FACTOR_NAMES):
        ff3 = _insufficient(MIN_OBS_FF3_REGRESSION)
    else:
        ff3 = _map_regression_result(
            ff3_regression(asset_returns, factors["mkt_rf"], factors["smb"], factors["hml"], rf)
        )

    return FactorsResponse(
        ticker=security.ticker,
        source=source,
        requested_start=start,
        requested_end=end,
        capm=capm,
        ff3=ff3,
        assumptions=_build_assumptions(rf_available=True),
    )


__all__ = ["compute_ticker_factors"]
