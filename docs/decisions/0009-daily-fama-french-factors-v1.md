# 9. Daily Fama-French factors for V1; schema supports monthly

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

Factor analysis needs a trusted factor-return series. Building factors from a
cross-section requires a survivorship-free universe and point-in-time
fundamentals - a project in itself. The Ken French data library publishes
official factors for free, in daily and monthly frequencies.

## Decision

V1 ingests the **daily** Fama-French research factors (Mkt-RF, SMB, HML) plus
the RF series, from the Ken French data library, into `factor_return`. Factor
regression is a full-sample OLS of daily excess returns on FF3 with
Newey-West (HAC) standard errors.

`factor_return` carries a `frequency` column (`'daily'` for V1) and its primary
key is `(factor_name, frequency, trade_date, source)`, so monthly factors, FF5
(RMW, CMA) and momentum can be added later as data, without schema change.

The FF regression's **Mkt-RF coefficient is not the user-facing SPY CAPM beta**
(ADR 0017): SPY is one S&P 500 ETF, FF Mkt-RF is the excess return of the broad
cap-weighted US market. Both are computed and reported, labelled distinctly.

## Consequences

- Daily data aligns naturally with the daily return series used elsewhere and
  gives ~250 observations/year for regression.
- Daily factor returns are noisier than monthly; the `assumptions` block reports
  frequency and `n`, and the regression enforces a minimum observation count.
- Home-grown factors remain a later research feature, not a V1 dependency.

## Alternatives considered

- **Monthly FF factors** - deferred: fewer observations for a multi-year window;
  schema keeps the door open.
- **Compute factors in-house for V1** - rejected: needs survivorship-free
  membership + PIT fundamentals; disproportionate for the MVP.
