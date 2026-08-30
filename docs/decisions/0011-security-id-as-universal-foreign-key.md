# 11. `security_id` is the universal foreign key

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

Tickers are reassigned and reused over time (`FB` -> `META`; a defunct ticker
later reissued to a different company). Joining time series on ticker silently
corrupts long histories.

## Decision

`security` has an internal surrogate `id` (bigint PK). **Every** other table
(`price_bar`, `factor_return` where security-scoped, `fundamental_fact`, and all
future `portfolio*` / `backtest*` tables) references `security_id`, never a
ticker string. The current `ticker` lives only on `security`.

A `ticker_history` table (ticker valid-from/valid-to per `security_id`) is
deferred; when added, existing joins are unaffected because none of them use the
ticker.

Foreign keys to `security` use **`ON DELETE RESTRICT`**. A security is the stable
root of its historical observations, so deleting one that still has child rows
(e.g. `price_bar`) is refused. Lifecycle changes use `security.is_active` and
`security.delisted_date`, never row deletion.

## Consequences

- Ticker renames become a one-row update on `security` (plus a `ticker_history`
  row once that table exists); no data migration of series tables.
- Search resolves ticker/name -> `security_id` once, at the edge; everything
  downstream is id-based.
- Slightly less human-readable raw tables (an extra join to see the ticker) -
  acceptable.

## Alternatives considered

- **Ticker as natural key** - rejected: the corruption mode above is silent and
  unrecoverable.
- **`ticker_history` now** - deferred: no ticker changes in the demo set; the
  id discipline already captures the benefit.
