# 4. PostgreSQL with provenance fields; defer point-in-time tables

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

Future point-in-time analysis (backtesting without look-ahead, as-reported
fundamentals) requires knowing *when* and *from where* each datum arrived.
Provenance cannot be reconstructed after the fact. At the same time, the MVP
does not need the full point-in-time machinery.

## Decision

Use PostgreSQL via SQLAlchemy 2.0 + Alembic. The MVP schema is five tables:
`security`, `price_bar`, `factor_return`, `fundamental_fact`,
`data_ingestion_run`.

Carry these columns from the first migration:

- `source` and `ingested_at` on every externally sourced row.
- `filed_date`, `accession_no`, `form` on `fundamental_fact`; restatements are
  inserted as new rows, never updates.
- `trade_date` stored as a calendar `date` (not a timestamp); all instants are
  `timestamptz` in UTC.
- Both raw `close` and vendor `adj_close` on `price_bar` (see ADR 0012).

Defer the tables that are not yet exercised: `ticker_history`,
`corporate_action`, `risk_free_rate`, `valuation_snapshot`, `benchmark_price`,
`provider_request_log`, and all `portfolio*` / `backtest*` / `filing*` / `ai_*`
tables. Each is a later additive migration.

## Consequences

- No expensive backfill later: the irreplaceable metadata is already there.
- The MVP schema stays small enough to hold in your head.
- Some fundamentals queries in the MVP show "latest available" rather than
  strict as-of; the data to do it properly is nonetheless being stored.

## Alternatives considered

- **SQLite for V1** - rejected: `pg_trgm` search, richer types, and prod parity
  are worth the container.
- **Store only vendor-adjusted prices** - rejected: raw + actions is the only way
  to recompute adjustments correctly later.
- **Full point-in-time schema now** - rejected: unused complexity; violates the
  "no speculative abstraction" principle.
