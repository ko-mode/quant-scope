# 5. `assumptions` metadata block in every analytics response

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

A Sharpe ratio or VaR figure is meaningless - and unverifiable - without the
window, calendar, annualisation factor, risk-free rate and return convention
behind it. Reproducibility is a core project principle.

## Decision

Every analytics response embeds an `assumptions` object. Minimum fields:

- `as_of`, `window` (start/end + rolling length where relevant)
- `calendar` (e.g. `"XNYS"`), `annualisation_factor` (`252`)
- `return_type` (`"total"` | `"price"`)
- `rf_source` and the effective `rf` value used
- `benchmark` (ticker) and `market_proxy` where beta/relative metrics are
  present - and, for factor results, a note that the FF Mkt-RF coefficient is a
  different quantity from the SPY CAPM beta (ADR 0017)
- `var_horizon_days` (`1`) and `var_scaling` (`"none"`) for VaR/ES;
  `confidence_levels` (`[0.95, 0.99]`)
- `data_source`, `missing_data_policy`
- `observations_used`; for comparisons, `aligned_start` and `aligned_end`
- `min_observations` thresholds applied, and a `suppressed` list of
  `{metric, status, required, observations_used}` for any metric withheld for
  insufficient data (ADR 0017)
- for Sharpe, an `annualisation_note` flagging the sqrt(252) i.i.d. assumption
  and return-autocorrelation caveat

The block is assembled by the service layer, not the pure engine. Frontend
surfaces it as first-class "methodology" content, not a hidden tooltip.

## Consequences

- Any number in the UI can be independently recomputed from its response.
- Response payloads are slightly larger and the DTOs carry an extra nested model.
- Changing a default (e.g. annualisation) is visible in the payload rather than
  silent.

## Alternatives considered

- **Document assumptions only in API docs** - rejected: drifts from behaviour and
  is invisible per-response.
- **Separate `/methodology` endpoint** - rejected: couples two calls and invites
  mismatch.
