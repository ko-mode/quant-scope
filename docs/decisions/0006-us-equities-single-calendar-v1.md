# 6. US equities and a single exchange calendar (XNYS) for V1

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

Multi-exchange, multi-currency support multiplies correctness hazards:
non-synchronous closes, holiday-calendar mismatches, FX conversion, and
session-alignment bugs that silently leak or misalign returns.

## Decision

V1 covers US-listed equities and ETFs only, priced in USD, on the XNYS trading
calendar (via `exchange_calendars`). Ingestion asserts these constraints and
rejects violations rather than coercing them. Time-series alignment uses the
XNYS session index, not a naive date range; missing sessions are explicit.

## Consequences

- One calendar, one currency: return alignment, annualisation and beta are
  straightforward and testable.
- ADRs, non-US listings and FX are out of scope until a dedicated phase adds
  per-security calendar/currency and a conversion layer.
- The `security` table still stores `exchange` and `currency` so the constraint
  is data-visible and later relaxation is additive.

## Alternatives considered

- **Global coverage in V1** - rejected: correctness risk far exceeds MVP value.
- **Calendar-free (all weekdays)** - rejected: injects fake trading days and
  distorts every annualised statistic.

## Addendum (2026-09-07, release-remediation pass - QS-01)

This decision's "missing sessions are explicit" clause was accepted but not
enforced anywhere in code - `quantscope.quant.returns.simple_returns` computed
a return across any two consecutive price rows regardless of whether an XNYS
session actually fell between them, so a gap in ingested history (a bad
provider response, a manual backfill skipping days) silently produced one
return implicitly spanning multiple trading days. Two mechanisms now close
this, deliberately kept separate because they answer different questions:

- **Row rejection at ingestion** (`quantscope.data.validation`, a new
  `_valid_xnys_session` Pandera check on `PRICE_BAR_SCHEMA`'s `trade_date`
  column, error code `non_session_trade_date`): a persisted price row whose
  date is not a real XNYS session (weekend, holiday, or any other malformed
  date) is rejected the same way a non-positive price is - it never reaches
  the database. This answers "is this date a real trading day at all?" and
  never fires for a genuine gap between two otherwise-valid sessions.
- **Return-adjacency suppression** (new module
  `quantscope.data.calendar`): `valid_session_mask` backs the ingestion
  check above; `valid_return_adjacency_mask` and `session_continuous_returns`
  are applied by every service (`analytics.py`, `comparison.py`,
  `factors.py`) in place of a bare `simple_returns(prices)` call on an actual
  security's price series. This answers a different question - "does the
  return between two already-valid prices span an expected session that is
  missing from the data?" - and excludes only that one return adjacency.

**The price bars themselves are never touched, dropped, or flagged by the
second mechanism.** A valid price immediately after a gap is not itself
invalid data; it still anchors the *next* return normally. Only the specific
return that would otherwise silently compress a missing session into a single
trading day's move is excluded from the series that reaches every downstream
metric (return summary, volatility, drawdown, Sharpe, beta, VaR/ES,
comparison, CAPM/FF3 regression).

This rejects the alternative of either (a) rejecting an otherwise-valid full
history outright because one session is missing, or (b) interpolating or
forward-filling the missing session's price - both would fabricate data this
ADR's "missing sessions are explicit" clause was written to prevent. Ken
French factor series are unaffected: they are already daily returns, not
derived from a price series, and carry no XNYS session concept.

Deliberately implemented in `quantscope.data`, not `quantscope.quant` (ADR
0002): the pure engine is calendar-agnostic by design and also processes
non-XNYS-anchored factor series, so calendar knowledge belongs in the data
layer, which already carries `security.exchange`.
