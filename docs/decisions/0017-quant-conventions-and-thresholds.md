# 17. Quantitative conventions and observation thresholds (V1)

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

Every user-facing statistic needs one fixed, documented convention. Ambiguity
about annualisation, which market proxy defines "beta", VaR horizon and scaling,
and how short histories are handled leads to numbers that cannot be reproduced or
compared.

## Decision

All constants live in one module (`quantscope.quant.conventions`) and every
affected response echoes them in its `assumptions` block (ADR 0005).

### Returns
Total return from adjusted close (ADR 0012). Simple returns for aggregation /
compounding; log returns only where a function's maths requires additivity,
documented per function.

### Volatility
Sample standard deviation (`ddof=1`) of daily total returns, annualised by
**sqrt(252)**.

### Sharpe ratio
`mean(daily excess return) / stdev(daily excess return) * sqrt(252)`, with
daily excess return = daily total return - daily Ken French `RF`. Documented as
an **annualisation convention**: sqrt(252) assumes i.i.d. daily returns, so
return autocorrelation biases the annualised value (positive inflates, negative
deflates). Reported, not corrected, in V1.

### Beta (user-facing / CAPM)
OLS slope of the security's daily excess return on **SPY's** daily excess
return, both from **total-return-adjusted** prices, over the requested window,
`RF` = Ken French `RF`.

### Fama-French 3-factor regression
OLS of the security's daily excess return on Ken French **Mkt-RF, SMB, HML**
with **Newey-West (HAC)** standard errors.

**The SPY CAPM beta and the FF Mkt-RF coefficient are different quantities.**
SPY is one S&P 500 ETF; FF Mkt-RF is the excess return of the broad cap-weighted
US market (all listed common stock, dividends and delistings included). Both are
computed and reported, labelled distinctly; neither is "the" beta.

### Historical VaR / Expected Shortfall
- **1-trading-day horizon only** in V1, historical (empirical) method.
- `VaR_alpha = -(empirical (1 - alpha) quantile of daily total returns)`,
  reported as a **positive loss**.
- `ES_alpha = -(mean of daily returns at or below that quantile)`.
- **No square-root-of-time or any multi-day scaling.**
- Confidence levels reported: **95% and 99%**.

### Minimum observation thresholds
Centralised. A metric with fewer usable daily observations than its threshold is
**suppressed**, and the response carries
`{metric, status: "insufficient_observations", required, observations_used}`.

| Threshold | Metrics gated                                             |
|-----------|----------------------------------------------------------|
| **60**    | returns, annualised volatility, drawdown / max drawdown   |
| **126**   | Sharpe, beta, historical VaR, historical ES               |
| **250**   | FF3 regression                                            |

### Multi-security comparison
One **common trading-date panel**, built by **inner join** on trading date
across every requested security (plus SPY / FF factors where needed). The
correlation matrix and all cross-security betas are computed from that single
panel. **No pairwise-complete / pairwise-deletion correlation in V1.** The
response exposes `observations_used`, `aligned_start`, `aligned_end`.

## Consequences

- Numbers are reproducible from the `assumptions` block and comparable across
  securities.
- A short-history security shrinks the common window for a whole comparison -
  intentional and shown to the user.
- Some metrics are withheld on short windows rather than shown unreliably.
- Multi-day risk horizons are explicitly out of scope until a defensible method
  is added.

## Alternatives considered

- **sqrt-time scaling for a 10-day VaR** - rejected for V1: unjustified for
  fat-tailed daily returns; better to ship 1-day only.
- **Pairwise-complete correlation** - rejected: mixes windows across pairs,
  producing a matrix that need not be positive semidefinite and is hard to
  explain.
- **Per-metric configurable thresholds via API** - deferred: fixed, centralised
  values are simpler and enough for V1.

## Addendum (2026-09-04, Phase 2A implementation)

Clarifications settled while building `quantscope.quant`. The decision above is
unchanged; these only pin down details it left open.

- **Simple-return convention.** Daily return `r_t = P_t / P_{t-1} - 1` from the
  adjusted close; the first price yields no observation. No log returns in the
  V1 user-facing path.
- **VaR / ES quantile estimator.** The empirical `(1 - alpha)` quantile is the
  *lower* order statistic, no interpolation: sorted ascending, index
  `floor((1 - alpha)(n - 1))`. Tie-safe and always an observed return. The ES
  tail is `r_t <= r*` (inclusive). No flooring at zero, so an all-gains tail
  can report a negative VaR.
- **Scalar risk-free convenience.** The Sharpe interface takes a daily `RF`
  series; a scalar *annual* rate, if given, is compounded to a daily rate,
  `(1 + r)^(1/252) - 1`, never divided by 252.
- **Undefined vs suppressed vs rejected.** A zero-variance denominator (Sharpe
  daily excess, CAPM benchmark excess) returns an explicit
  `status: "undefined"`. A structurally invalid series (bad index, unsorted or
  duplicated dates, non-finite values, non-positive prices) raises. `status:
  "insufficient_observations"` is reserved for a well-formed series shorter than
  its gate.
- **CAPM `r_squared` when the asset's excess return is constant.** The
  regression is still valid (benchmark varies, so beta and alpha are defined and
  returned), but `R^2 = 1 - SS_res / SS_tot` is `0 / 0`. `BetaResult.r_squared`
  is therefore `float | None` and is `None` in this case - matching
  `statsmodels`, which yields `nan` for a zero total sum of squares. It is *not*
  clamped to `0.0` (that is a `scikit-learn` pipeline convenience, documented in
  its own API as "not finite / not interesting", not a statistical convention).
  A constant *benchmark* excess return is different: beta itself is undefined,
  so the whole result is `UndefinedResult`.
- **Drawdown recovery.** The result reports the running-peak date, the trough
  date and - when wealth regains the peak within the window - the recovery
  date. A series that never draws down reports `max_drawdown = 0.0` with null
  peak / trough / recovery dates (no episode occurred).
- **Suppression object field names.** `InsufficientObservations(metric,
  required, observations_used, status)` - the wire names from this ADR, carried
  unchanged from the engine through to the response (no internal renaming).

## Addendum (2026-09-05, Phase 3B implementation - CAPM regression + FF3 with HAC)

Clarifications settled while building `quantscope.quant.factors`. The
Fama-French 3-factor decision above is unchanged; this pins down the CAPM
regression's regressor, the Newey-West lag rule, the pre-fit check order, and
alpha's annualisation status - none of which the original decision or its
2026-09-04 addendum specified.

- **Phase 3B's "CAPM regression" uses SPY, not Mkt-RF.** It is the same
  economic model as the existing user-facing beta above
  (`R_i - RF = alpha + beta_SPY * (R_SPY - RF) + eps`), computed by a new
  function (`quant.factors.capm_regression`) that adds full OLS/HAC
  inference (standard error, t-statistic, p-value, 95% CI) that
  `risk.capm_beta` does not compute. `risk.capm_beta` itself, and the Risk &
  Return "Beta vs SPY" metric it backs, are **unchanged**. There is no
  regression in this codebase, anywhere, that treats Mkt-RF as "the CAPM
  market factor" - Mkt-RF only ever appears as one of the three FF3 factors.
- **Newey-West (HAC) lag rule**: `L = floor(4 * (T/100) ** (2/9))`, minimum
  1 - the Newey & West (1994) plug-in bandwidth, a deterministic function of
  the sample size `T` (`observations_used`) alone. Implemented as
  `quant.factors.newey_west_lags` and recorded verbatim as `hac_lags` on
  every successful result, never a hidden library default.
- **One fitted OLS model, not two.** `sm.OLS(y, X).fit(cov_type="HAC",
  cov_kwds={"maxlags": L, "use_correction": True})` supplies both the
  coefficients (`cov_type` changes only the covariance estimate, never the
  point estimates) and the HAC-based inference from that same fit. There is
  no separate classical-OLS fit anywhere, and no classical-OLS standard
  error is exposed on the wire - HAC-only inference, per the original
  decision's text above.
- **Alpha is never annualised**, for either regression - reported only as
  the daily intercept, exactly like `BetaResult.alpha_daily`. No
  `alpha_annualized` field exists anywhere (quant dataclass, API schema,
  service mapping, or frontend).
- **Explicit pre-fit checks, in this order** - neither relies on
  `statsmodels.add_constant(..., has_constant="raise")`:
  1. Each regressor's own variance, checked individually. A constant
     regressor (e.g. a zero-variance `SMB` window) returns
     `UndefinedResult(metric, "regressor '<name>' has zero variance", n)`,
     naming the offending regressor.
  2. Only if every regressor varies: the assembled design matrix's rank
     (`numpy.linalg.matrix_rank`). A rank-deficient design from otherwise-
     varying, collinear regressors returns
     `UndefinedResult(metric, "design matrix is rank-deficient", n)`.

  A constant *dependent* variable (the asset's excess return) is not an
  `UndefinedResult` - matching the existing `capm_beta` precedent, the
  regression stays valid (`r_squared`/`adjusted_r_squared` become `None`,
  the `0/0` case, never `0.0`).
- **CAPM regression gate**: `MIN_OBS_CAPM_REGRESSION = MIN_OBS_BETA = 126` -
  reused rather than a new number, since it is the same regression family as
  the existing beta. FF3's `MIN_OBS_FF3_REGRESSION = 250` is unchanged.

## Addendum (2026-09-07, release-remediation pass - QS-02, drawdown peak date)

The "Drawdown recovery" clause in the 2026-09-04 addendum above states the
running peak/trough/recovery dates but did not settle what `peak_date` should
be in the specific case where the maximum drawdown's governing peak is the
**pre-return wealth anchor of 1.0** itself - i.e. the return series opens with
a loss, so wealth never rises back to 1.0 at any date *within*
`returns.index` before the trough. That anchor is real (it is the wealth
immediately before the first return) but has no date inside the return
series's own index, so reporting a `peak_date` for it requires a date the
quant engine was never given.

`drawdown_analysis` now takes an optional `anchor_date: pd.Timestamp | None`
keyword. The service layer (`services/analytics.py`) supplies the price date
immediately preceding `returns.index[0]` - i.e. `prices.index[0]`, one date
earlier, already available from the same price series the service loaded to
compute `returns` in the first place, so no additional query or architectural
change was needed to obtain it. When the running peak is the anchor,
`peak_date` is reported as this truthful preceding price date rather than a
placeholder.

`anchor_date` is optional, not required, because `quant/drawdown.py` is also
called with a bare return series in unit tests and in any future context that
does not have a price index at hand: when omitted, `peak_date` is `None`,
meaning specifically "the peak precedes the first available return
observation" - a distinct condition from `max_drawdown == 0.0` (no drawdown
episode occurred at all), which continues to report `peak_date = None` for
its own, different reason. The two `None` cases are never conflated in code:
`max_drawdown` alone distinguishes them, and both are documented and tested
independently (`backend/tests/unit/quant/test_drawdown.py`).

The running maximum was also corrected to include the anchor value:
`wealth.cummax().clip(lower=1.0)` rather than a bare `wealth.cummax()`, so
that a return series opening with one or more losses is correctly recognised
as itself being a drawdown from the anchor, not understated by comparing
wealth only against its own (already-diminished) running maximum.
