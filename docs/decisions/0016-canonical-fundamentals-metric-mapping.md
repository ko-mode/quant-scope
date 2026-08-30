# 16. Canonical-metric mapping for fundamentals

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

SEC EDGAR CompanyFacts does not expose one universal tag per financial concept.
Revenue appears as `Revenues`,
`RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet` and
others depending on the filer and period; diluted EPS as
`EarningsPerShareDiluted` or `EarningsPerShareBasicAndDiluted`; and so on.
Assuming a single tag silently produces wrong or missing numbers for many
issuers.

## Decision

Phase 3 introduces an explicit **canonical-metric mapping layer**
(`quantscope.data.canonical_metrics`). For each displayed metric (revenue, net
income, diluted EPS, shares outstanding, ...) it defines a **small ordered list**
of accepted `(taxonomy, tag, unit)` tuples.

Resolution: for a requested period, walk the ordered list and take the first
tuple that has a value. Record the `tag`, `accession_no`, `filed_date`, `form`
and `period_end` that were actually used, and return them with the value.

If **no** mapped tuple is present, the metric is returned as **`unavailable`**
with a structured reason (`{metric, status: "no_mapped_tag", candidates_tried}`).
**No heuristic fallback** (largest value, fuzzy tag match, cross-period
inference).

`fundamental_fact` retains `taxonomy`, `tag`, `unit`, `filed_date`,
`accession_no` and `form` on every row; restatements are new rows.

## Consequences

- Every displayed fundamental is auditable back to a specific XBRL tag and
  filing.
- Some metrics are `unavailable` for some issuers/periods; the UI shows that
  honestly rather than a wrong number.
- The mapping lists need occasional maintenance as taxonomies evolve - a small,
  reviewed, well-tested surface.

## Alternatives considered

- **Single canonical tag per metric** - rejected: silently wrong for a large
  fraction of filers.
- **Heuristic (pick the largest / most recent matching-looking tag)** - rejected:
  unauditable and produces confident nonsense.
- **Full XBRL calculation-linkbase resolution** - deferred: heavy; the ordered
  allowlist covers the displayed metrics.
