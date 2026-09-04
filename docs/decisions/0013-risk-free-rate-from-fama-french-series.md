# 13. Risk-free rate from the Ken French `RF` series

- **Status:** Accepted - **implemented** (Phase 2B.1, 2026-09-04)
- **Date:** 2026-08-30

## Context

Sharpe ratio, Sortino and excess-return factor regressions all need a
risk-free-rate time series. The Ken French research-factors file already
distributes a daily `RF` column alongside Mkt-RF/SMB/HML, which V1 ingests
anyway (ADR 0009).

## Decision

Store the Ken French daily `RF` series as rows in `factor_return` with
`factor_name = 'rf'`. Sharpe and regression excess returns read RF from there.
Do **not** create a dedicated `risk_free_rate` table for V1. The `assumptions`
block reports `rf_source = "kenneth_french_daily"` and the effective rate used.

## Consequences

- One ingestion (FF factors) supplies both the factors and the risk-free rate;
  one fewer table and provider.
- RF is tied to the FF release cadence and definition (1-month T-bill), which is
  exactly what the FF regressions assume - internally consistent.
- If a different RF (e.g. FRED 3-month T-bill, or a term-matched rate) is wanted
  later, add a `risk_free_rate` table and switch `rf_source`; the reader
  abstraction in the service layer localises the change.

## Alternatives considered

- **FRED T-bill series + own table now** - deferred: extra provider and table
  for no MVP benefit; less consistent with the FF regressions.
- **Constant RF from config** - rejected: wrong across multi-year windows and
  hides a real assumption.

## Addendum (2026-09-04, Phase 2B analytics API)

The Phase 2B analytics endpoint (`GET /securities/{ticker}/analytics`) ships
before Ken French factor ingestion and migration M2, so `factor_return` - and
therefore the `RF` series this ADR mandates - does not exist yet.

Rather than substitute a constant or zero RF (which this ADR rejects), the
analytics service **withholds both metrics that depend on RF**: Sharpe *and*
CAPM beta are returned with `status: "unavailable"`,
`reason: "risk_free_series_not_ingested"`, and `assumptions.rf` is `null` with
`rf_source: "none_pending_fama_french_ingestion"`. The other metrics (return
summary, volatility, drawdown, historical VaR/ES) are unaffected.

`quantscope.services.analytics._load_daily_risk_free(session, start, end)` is
the reader seam this ADR anticipated ("the reader abstraction in the service
layer localises the change"). It returns `None` today; M2 makes it read the
daily `RF` rows from `factor_return`, at which point Sharpe and beta become
`ok` with **no change to the route, the schema, or the engine**. When that
lands, `rf_source` becomes `"kenneth_french_daily"` per the decision above.

## Addendum (2026-09-04, Phase 2B.1 - implemented)

Migration `0003_factor_return` and `quantscope.data.factor_ingest` /
`quantscope.data.providers.french_factors` (ADR 0009) now populate
`factor_return` from the live Kenneth French daily FF3 file
(`just ingest-factors`). The interim state described in the addendum above is
resolved:

- `_load_daily_risk_free` reads real `factor_name='rf', source='kenneth_french'`
  rows and returns a `pandas.Series` when any exist for the window, `None`
  otherwise (an empty/not-yet-ingested table, unchanged fallback behaviour).
- Sharpe and CAPM beta now transition through their full status range:
  `ok` (RF present, enough overlap), `insufficient_observations` (RF present,
  overlap below the ADR 0017 gate), `undefined` (zero excess-return / zero
  benchmark-excess variance), and `unavailable` only when RF (or, for beta,
  SPY) is genuinely absent - never a fabricated constant/zero rate.
- `assumptions.rf_source` is `"kenneth_french_daily"` and `assumptions.rf_basis`
  is `"daily_series"` once RF is ingested; `"not_ingested"` / `null` otherwise.
  `assumptions.rf` stays `null` in both cases - RF is a time series, never a
  scalar, so there is no single "effective rate" to report.
- A live ingestion (2026-09-04) persisted 105,096 rows (26,274 trading dates x
  4 factors, 1926-07-01 to 2026-06-30) with zero dropped rows; a re-run
  inserted 0 / updated 0 / left 105,096 unchanged, confirming idempotency
  against the real file.
