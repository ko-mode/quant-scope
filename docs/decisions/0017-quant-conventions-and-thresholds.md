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
