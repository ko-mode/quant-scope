# 9. Daily Fama-French factors for V1; schema supports monthly

- **Status:** Accepted - ingestion **implemented** (Phase 2B.1, 2026-09-04); FF3
  regression itself remains Phase 3B
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

## Addendum (2026-09-04, Phase 2B.1 - ingestion implemented)

`quantscope.data.providers.french_factors.KennethFrenchDailyFactorProvider`
downloads the daily `F-F_Research_Data_Factors_daily_CSV.zip`, and
`parse_ff_daily_factors` locates the header row **structurally** (the first
line containing all of `Mkt-RF, SMB, HML, RF`) rather than assuming a fixed
preamble length, so a future reformatting of the file's descriptive text does
not break ingestion. `quantscope.data.factors.normalize_factor_returns`:

- rejects the Kenneth French missing-value sentinels (`-99.99`, `-999`) as a
  structured `missing_factor_value` error rather than persisting them;
- **converts the source's percent units to decimal daily returns**,
  `value_decimal = value_percent / 100` (e.g. `0.25` -> `0.0025`), before any
  row reaches `factor_return`. Stored `value` is always a decimal daily return,
  never a percent.

A separate heuristic, `abs(value) < 0.5` (Pandera, `FACTOR_RETURN_SCHEMA`),
catches a forgotten percent-to-decimal conversion (a real daily Mkt-RF stays
within roughly +/-18% even on 1929/1987/2020-scale days). This is deliberately
**not** a database CHECK constraint - the database enforces structural
integrity only; the ingestion / validation layer owns unit-confusion
heuristics, so the bound can be revisited without a migration.

`quantscope ingest-factors` (`just ingest-factors`) is idempotent - a rerun
against unchanged source data inserts and updates nothing, mirroring the
Phase 1D price-bar upsert semantics. A live run on 2026-09-04 persisted
105,096 rows (26,274 daily dates x 4 factors, 1926-07-01 to 2026-06-30) with
zero rows dropped.
