# 22. Price provider: Stooq reassessed; Tiingo recommended for real ingestion

- **Status:** Accepted
- **Date:** 2026-08-30
- **Amends:** ADR 0008 (Stooq as initial price provider)

## Context

ADR 0008 chose Stooq as the first `PriceProvider` (tokenless, CSV over HTTP).
Phase 1C reassessed Stooq before implementing the adapter, as ADR 0008 itself
flagged concerns about adjusted-close semantics and reliability.

## Findings

1. **Anti-bot gating (verified 2026-08-30).** Every Stooq data URL
   (`stooq.com/q/d/l/`, `stooq.pl/...`, the light-quote endpoints) responds
   `HTTP 200` with a JavaScript proof-of-work *"This site requires JavaScript to
   verify your browser"* challenge page - **not CSV**. A plain HTTP client
   cannot retrieve data. Confirmed with `curl` and `httpx` for `NVDA` and `SPY`.
2. **Single, ambiguous `Close`.** Stooq's daily CSV has one `Close` column and
   no separate raw/unadjusted price; its adjustment rule (split-only vs
   split+dividend) is undocumented. Mapping it to both `close` and `adj_close`
   makes ADR 0012's "recompute adjustment from stored raw close" impossible with
   Stooq data.
3. **Rate limits.** Historically ~50-100 requests/day per IP, then a
   `"Exceeded the daily hits limit"` body.
4. **Redistribution.** Stooq's terms forbid redistribution - consistent with
   ADR 0015, but it means tests use **synthetic hand-authored** fixtures, not
   recorded cassettes (this supersedes ADR 0008's "recorded cassettes" plan).

## Decision

* **Implement the Stooq adapter for Phase 1C** behind the `DailyPriceProvider`
  Protocol. Phase 1C's real deliverable is the provider contract + the
  normalisation / Pandera-validation / spot-check layers, all provider-agnostic;
  the adapter exercises the contract.
* The adapter **detects the browser-verification challenge and raises
  `PriceProviderBlockedError`**. It is fully unit-tested with synthetic CSV, but
  **cannot be verified against a live Stooq response** while the gating stands.
  The NVDA split spot-check therefore runs against a hand-authored fixture only.
* **Recommend Tiingo as the price provider from Phase 1D**: free token
  (email sign-up), JSON with `close` **and** `adjClose` (plus `adjOpen/High/Low`,
  `divCash`, `splitFactor`), documented semantics, ~1000 req/day. It satisfies
  ADR 0012 (real raw + adjusted) and drops in behind the unchanged Protocol.
* ADR 0008 is amended: Stooq is no longer the assumed source for real ingestion,
  and test doubles are synthetic fixtures, not cassettes.

## Consequences

* Phase 1C is complete and provider-independent: `DailyPriceProvider`,
  `RawPriceBar`, `normalize_price_bars`, `PRICE_BAR_SCHEMA` / `validate_price_bars`,
  `check_nvda_split_adjustment`.
* **No live price data flows** until Phase 1D wires a working provider (Tiingo,
  or a JS-capable Stooq fetch path). This is a known gap, not a silent one.
* If Stooq ever is the source, every `price_bar` would have `close == adj_close`
  and ADR 0012's reconstruction path stays closed until a raw-close source
  (Tiingo) is used.

## Alternatives considered

* **yfinance** - rejected in ADR 0008 (unofficial, fragile, adjustment bugs);
  still not a system of record. Possible dev-only fallback.
* **Alpha Vantage** - 25 requests/day on the free tier; unusable for iteration.
* **Keep waiting on Stooq** - rejected: the gating is not under our control.
* **Headless-browser fetch for Stooq** - rejected: disproportionate infra for a
  dev data source when Tiingo solves it with a token.
