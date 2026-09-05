# 23. Factors API: one endpoint returns both CAPM and FF3

- **Status:** Accepted
- **Date:** 2026-09-05

## Context

Phase 3B exposes the SPY CAPM regression and the Fama-French 3-factor
regression (ADR 0017 addendum, 2026-09-05) via a new endpoint. An early sketch
in `docs/architecture.md` §8 described `GET /securities/{ticker}/factors?
model=ff3` - one model selected per request. Building the Factors frontend
tab (which shows both models together, per ADR 0019's "done properly"
priority on this feature) makes that shape awkward: either two round trips
per page view, or a client-side cache key per model.

A second open question was whether the existing `MetricStatus` four-way
vocabulary (`ok` / `insufficient_observations` / `undefined` / `unavailable`)
or the flatter three-way `ComparisonStatus` (no `undefined`) was the right
precedent for a *whole regression model's* status, given `undefined` is a new
concept at that granularity (previously it only applied to a single scalar
metric).

## Decision

`GET /securities/{ticker}/factors?start=&end=&source=` returns **both**
models in one response:

```json
{
  "ticker": "NVDA", "source": "tiingo", "adjustment_basis": "adjusted_close",
  "requested_start": null, "requested_end": null,
  "capm": { "status": "ok", "...": "..." },
  "ff3": { "status": "ok", "...": "..." },
  "assumptions": { "capm_vs_ff3_note": "...", "...": "..." }
}
```

There is no `model` query parameter. This mirrors `AnalyticsResponse`'s
existing pattern of bundling several related computations into one response
object (return summary, volatility, Sharpe, beta, VaR/ES) rather than one
endpoint per metric.

`FactorModelStatus` is **four-valued**, applied independently to `capm` and
`ff3`, preserving the same semantic distinction `MetricStatus` already makes
for a single scalar metric - not the flatter three-valued `ComparisonStatus`:

- `unavailable` - a required *input* is missing before alignment is even
  attempted (asset price history, the risk-free series, or - FF3 only - one
  of Mkt-RF/SMB/HML never ingested for the source).
- `insufficient_observations` - every required input is present, but the one
  common aligned sample is shorter than the model's gate.
- `undefined` - the aligned sample clears the gate, but the regression itself
  is not estimable (a zero-variance regressor, or a rank-deficient design).
  **Never** collapsed into `unavailable` - a quant-layer `UndefinedResult`
  maps 1:1 to `status: "undefined"`.
- `ok` - the model is estimable.

Additionally, coefficient-level inference fields (`std_error` / `t_stat` /
`p_value` / `ci_low` / `ci_high`) may independently be `null` even when the
whole model's `status == "ok"`, when the OLS `estimate` exists but that one
statistic is undefined for it (e.g. a HAC standard error of exactly zero).
This is a finer-grained null than the whole-model status and is new - no
earlier response shape needed per-field undefined-ness inside an otherwise-ok
result.

`docs/architecture.md` §8's `?model=ff3` sketch is superseded by this ADR.

## Consequences

- The Factors tab renders CAPM and FF3 simultaneously from one query, with no
  extra round trip and no per-model cache key.
- CAPM and FF3 can (and do) have different statuses in the same response -
  e.g. a security with 126-249 aligned observations gets `capm: ok` and
  `ff3: insufficient_observations` together. Frontend code must render each
  model's status independently, never assume they match.
- A whole-regression `undefined` state exists in the wire schema and must be
  rendered distinctly from `unavailable` in the UI (different title text,
  different meaning: "not enough overlapping history" tells the user to
  widen the range; "not estimable" tells them the *data itself*, not the
  window, is the problem).
- If a future phase adds more factor models, they slot into the same
  response object (a new named field, e.g. `"ff5"`) rather than a new
  `?model=` request.

## Alternatives considered

- **`?model=ff3` / `?model=capm`, one model per request** (the original
  sketch) - rejected: forces two requests for the Factors tab's simultaneous
  display, and a `model` selector adds a second query-key dimension to
  `useSecurityFactors` for no benefit once both models are always wanted
  together.
- **Three-valued `FactorModelStatus`, matching `ComparisonStatus`** (fold
  `undefined` into `unavailable`) - rejected: loses the distinction between
  "an input is missing" (fixable by ingesting more data) and "the regression
  itself cannot be estimated on this data" (not fixable by ingesting more of
  the same series) - a distinction ADR 0017's addendum already establishes
  at the single-metric level and that this feature should not regress.
