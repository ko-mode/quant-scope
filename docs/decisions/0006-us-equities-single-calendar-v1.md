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
