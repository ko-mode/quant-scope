# 22. Price provider: Tiingo adopted as V1 live provider

- **Status:** Accepted
- **Date:** 2026-08-30 (Tiingo adopted 2026-08-31 after the provider review;
  live-verified 2026-09-02)
- **Amends:** ADR 0008 (Stooq as initial price provider)

## Context

ADR 0008 chose Stooq. Phase 1C reassessed it before implementing the adapter,
found Stooq unusable for automated ingestion, and (2026-08-31) a dedicated
market-data provider review compared realistic free-tier alternatives (Tiingo,
Twelve Data, Alpha Vantage, EODHD, Polygon, yfinance). **Tiingo is adopted as
QuantScope's V1 live daily-price provider.**

## Findings

### Stooq (incumbent) - unusable for automated ingestion

1. **Anti-bot gating (verified 2026-08-30).** Every Stooq data URL responds
   `HTTP 200` with a JavaScript proof-of-work *"verify your browser"* challenge
   page - not CSV. A plain HTTP client cannot retrieve data. Confirmed with
   `curl` and `httpx` for `NVDA` and `SPY`.
2. **Single, ambiguous `Close`.** One column, no separate raw/adjusted, no
   documented adjustment rule.
3. Historically ~50-100 requests/day per IP.
4. Terms forbid redistribution.

### Tiingo - adopted

- **History:** US equities to 1962; **30+ years on the free tier**.
- **Fields:** raw `open/high/low/close/volume` **and** `adjClose` (+
  `adjOpen/High/Low/Volume`), plus `divCash` and `splitFactor` per row.
- **Adjusted-close semantics (from Tiingo's End-of-Day docs):** the adjustment
  "follows the standard method set forth by 'The Center for Research in Security
  Prices' (CRSP)… incorporates **both split and dividend adjustments**." A CRSP
  split-and-dividend back-adjusted close is a total-return series by
  construction, so `adjClose.pct_change()` is total return - **compatible with
  ADR 0012**. Raw `close` is retained separately, so ADR 0012's future
  self-computed reconstruction path stays open.
- **Auth:** one API token (`Authorization: Token <token>` header).
- **Free tier (checked 2026-08-31; time-sensitive):** 50 req/hour, 1000 req/day,
  500 unique symbols/month, 1 GB/month bandwidth; EOD prices + corporate actions
  included; email sign-up.
- **Demo universe:** NVDA, AMD, INTC, AAPL, MSFT and **SPY** all covered with
  full history. Plain-ticker symbols (dashes for share classes) - no mapping
  needed for the demo set.
- **Usage terms:** *"For Basic and Power accounts, data is for internal and
  personal use only. You may not redistribute the data in any form."* Storing
  fetched observations in the developer's **local** PostgreSQL is internal use
  and is **compatible**. Committing or publishing datasets is redistribution and
  is **prohibited** - exactly ADR 0015's posture; no ADR 0015 change.
- **Contract fit:** Tiingo JSON → adapter → `RawPriceBar` → the *existing*
  `normalize_price_bars` → the *existing* Pandera `PRICE_BAR_SCHEMA`. **No
  change to the provider-independent contract.** (`date`'s `T…Z` suffix is
  trimmed to a date string inside the adapter; `divCash`/`splitFactor` are not
  part of `RawPriceBar` and are dropped there.)

### Live verification (2026-09-02)

The guarded live suite (`tests/integration/live/`, run once with a free token)
confirmed the adoption empirically:

- **Dividend adjustment - confirmed.** On the AAPL ex-dividend session of
  **2024-05-10**, Tiingo reported `divCash = 0.25`; the
  `verify_dividend_back_adjustment` check independently implied a dividend of
  **~0.2500** from the raw vs. adjusted closes (adjusted return across the
  ex-date -0.688% vs. raw price return -0.824%). This empirically confirms that
  Tiingo `adjClose` incorporates dividend adjustment and is therefore suitable
  for the total-return analytics assumed by ADR 0012.
- **NVDA 10:1 split - confirmed.** The June 2024 split spot-check passed:
  `adj_close` is continuous across the 2024-06-10 ex-date (ratio ~0.99, no ~10x
  discontinuity), all reference points within tolerance.
- **Demo universe - fetched, normalised, validated.** All six demo tickers
  (NVDA, AMD, INTC, AAPL, MSFT, SPY) fetched ~10 years of history
  (2015-01-02 .. 2025-01-31), each yielding 2,536 bars that passed
  `normalize_price_bars` and the Pandera `PRICE_BAR_SCHEMA` with zero drops.

### Alternatives rejected

- **Twelve Data** (800 req/day free) - daily prices are **split-adjusted only**;
  dividend adjustment must be built from `/splits` + `/dividends`. Not a
  total-return series out of the box.
- **Polygon.io** - split-adjusted only; **no dividend adjustment**.
- **Alpha Vantage** - `TIME_SERIES_DAILY_ADJUSTED` is **premium-only**; the free
  tier gives raw OHLCV only and 25 req/day.
- **EODHD** - free plan capped at **~1 year of history**.
- **yfinance / Yahoo** - `Adj Close` semantics are fine, but it is an unofficial
  scrape being actively rate-limited/blocked in 2025-26; same failure class as
  Stooq. Rejected by ADR 0008 and still unsuitable.

## Decision

1. **Adopt Tiingo as the V1 live daily-price provider.** `price_provider`
   default is `tiingo`; `QUANTSCOPE_TIINGO_TOKEN` and `QUANTSCOPE_TIINGO_BASE_URL`
   configure it. A missing token raises `PriceProviderConfigError` at
   construction with instructions, not a later HTTP/parse failure.
2. **`TiingoDailyPriceProvider`** implements `DailyPriceProvider`; a pure
   `parse_tiingo_eod(...)` handles JSON→`RawPriceBar` mapping and is tested
   without HTTP. HTTP failures map into the provider error hierarchy:
   config/auth (`PriceProviderConfigError` / `PriceProviderAuthError`, both new
   `PriceProviderError` subclasses), 404 → `PriceDataUnavailableError`, 429 →
   `PriceProviderRateLimitedError`, empty result → `PriceDataUnavailableError`,
   non-JSON / network failure → `PriceProviderError`. httpx exceptions never
   leak past the adapter.
3. **Keep the Stooq adapter** as (a) evidence `DailyPriceProvider` supports
   multiple implementations, (b) an offline CSV parser, (c) the documented
   reason provider replaceability matters. It remains anti-bot blocked for
   automated live use.
4. **Tests use synthetic hand-authored fixtures only** (this supersedes ADR
   0008's "recorded cassettes"). No fetched Tiingo data is committed (ADR 0015).
5. **Empirical corporate-action checks** (Phase 1C.1):
   - `check_nvda_split_adjustment` against the NVDA 10:1 split (2024-06-10).
   - `verify_dividend_back_adjustment` - provider-independent arithmetic on
     `close`, `adjClose`, `divCash`, `splitFactor` around an ex-dividend date.
     It backs the dividend out of the adjustment and checks it matches the
     reported `divCash`, distinguishing a dividend-adjusted (total-return)
     series from a split-only one.
   Both run live in `tests/integration/live/` when `QUANTSCOPE_TIINGO_TOKEN` is
   set; a synthetic unit test proves the dividend-check logic either way.

## Consequences

* Phase 1C.1 is provider-adapter only - **no persistence, CLI, or APIs** (Phase
  1D-1E).
* `adj_close` continues to be the total-return series for analytics; this now
  rests on Tiingo's documented CRSP methodology plus an empirical check, not an
  assumption from a field name.
* Reproducibility for a fresh clone: free Tiingo signup → one token → one env
  var → guarded tests / (later) `just ingest-demo`.

## What is documentation vs. empirical vs. assumption

| Claim | Basis |
|---|---|
| Tiingo `adjClose` uses CRSP split **+ dividend** adjustment | Tiingo End-of-Day documentation (quoted above) |
| `adjClose.pct_change()` is a total-return series | follows mathematically from CRSP dividend back-adjustment; **confirmed empirically 2026-09-02** - the live `verify_dividend_back_adjustment` check on the AAPL 2024-05-10 ex-dividend session observed `divCash = 0.25` and independently implied a dividend of ~0.2500 from the raw/adjusted closes (see "Live verification" above) |
| Free-tier limits (50/hr, 1000/day, 500 sym/mo, 1 GB/mo) | Tiingo pricing page, **checked 2026-08-31**; time-sensitive, re-verify |
| Local DB storage is permitted; redistribution is not | Tiingo API overview "internal and personal use only… may not redistribute" |
| Dividend-adjustment factor is exactly `1 − dividend/close` | third-party docs mirror only; **not** verbatim-confirmed from a live Tiingo page - the empirical check does not depend on the exact factor |
| Credit card not required for the free tier | widely reported; not restated on the pricing page fetched |

## Addendum (2026-09-07, release-remediation pass - QS-06)

Point 3 above kept the Stooq adapter as a working, testable
`DailyPriceProvider` implementation, and `GET /securities/{ticker}/prices`
(`api/routers/securities.py`) still accepts `source=stooq` - it returns
whatever raw bars Stooq's offline CSV parser can produce, with no total-return
claim attached, which is exactly the "raw provenance-tagged price data" this
ADR's Findings section documents Stooq as being (a single ambiguous `Close`,
no dividend adjustment). That endpoint never asserted the data was
total-return-quality; the caller sees `source: "stooq"` and can judge it on
its own terms.

`/securities/{ticker}/analytics`, `/compare` (mounted at the root, not under
`/securities` - RA-05), and `/securities/{ticker}/factors`, however, all
compute or display statistics
that assume a total-return-adjusted series (ADR 0012) - annualised volatility,
Sharpe, CAPM/FF3 beta and alpha, drawdown, correlation. Stooq's single `Close`
column, per this ADR's own Findings, has "no documented adjustment rule" and
is not established to be dividend-adjusted the way Tiingo's `adjClose` was
empirically verified to be (see "Live verification" above). Accepting
`source=stooq` on these three endpoints would silently compute total-return
statistics from a series with no total-return guarantee, misrepresenting the
result's provenance without any signal to the caller.

Rather than build a general provider-capability framework (e.g. a
`supports_total_return: bool` flag per provider, consulted generically by
every analytics-bearing route) - which is more machinery than a V1 with two
providers, one of which is already the sole live-verified total-return source,
justifies - the fix is a literal type restriction:
`QuantitativeSource = Literal["tiingo"]` (`api/schemas.py`), used as the
`source` query-parameter type on exactly these three routers. A request for
`source=stooq` (or any value besides `tiingo`) on any of them now fails
FastAPI's own request validation with `422`, before the router body ever
runs - not a `200` with a suppressed/undefined metric, since the problem is
an invalid request, not thin data. `/prices` is untouched and keeps its
broader `PriceSource` type (`tiingo | stooq`), since it makes no total-return
claim.

If a second total-return-adjusted provider is added later, this becomes
`Literal["tiingo", "<new-provider>"]` - a one-line, self-documenting change at
the same three call sites, with no framework to design or migrate.
