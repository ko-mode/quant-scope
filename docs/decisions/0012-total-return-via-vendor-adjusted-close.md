# 12. Total return via vendor adjusted close

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

Return calculations must account for splits and dividends. Computing adjustments
in-house requires a reliable corporate-actions feed, which the free V1 sources
do not provide cleanly. Price-only returns understate equity performance
materially over multi-year windows.

## Decision

The default `return_type` for all analytics is **total return**, computed from
the vendor-supplied `adj_close` in `price_bar`. The raw `close` is also stored
on every row so a self-computed adjustment can replace the vendor one later
without re-ingesting history. The `assumptions` block always reports
`return_type` and `data_source`.

All total-return series - including **SPY**, used for the user-facing CAPM beta
(ADR 0017) - are built from `adj_close`.

A `corporate_action` table and in-house adjustment are deferred to a later
phase. Phase 1 adds a hand-authored spot-check of vendor adjustment behaviour
for the demo securities, explicitly the **NVDA 10-for-1 split (2024-06-10)**
(ADR 0015).

## Consequences

- Correct-enough total returns now, with no corporate-actions pipeline to build.
- Dependence on vendor adjustment quality; the ingestion validator flags
  implausible single-day moves (possible unadjusted splits) for review.
- Migrating to in-house adjustment later is isolated: add `corporate_action`,
  recompute an adjusted series from stored `close`, switch the source flag.

## Alternatives considered

- **Price returns for V1** - rejected: understates performance and distorts
  Sharpe/vol comparisons across names with different dividend yields.
- **In-house adjustment now** - rejected: needs a corporate-actions source and
  materially expands Phase 1-2 scope.
