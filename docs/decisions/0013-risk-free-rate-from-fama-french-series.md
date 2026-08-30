# 13. Risk-free rate from the Ken French `RF` series

- **Status:** Accepted
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
