# 8. Stooq as the initial price provider

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

V1 needs daily OHLCV for US equities/ETFs with the least setup friction, behind
an interface that a better source can replace without touching analytics.

## Decision

Use Stooq as the first `PriceProvider` implementation: no API key, simple CSV
over HTTP, split/dividend-adjusted close available. It is accessed only through
`quantscope.data.providers.base.PriceProvider`, whose contract is:

```
get_daily_bars(ticker: str, start: date, end: date) -> DataFrame  # validated by pandera
```

returning columns `trade_date, open, high, low, close, adj_close, volume`. No
Stooq-specific types or quirks leak past the implementation module. Provider
responses in tests are recorded cassettes; a separate nightly contract-test
suite hits the live endpoint.

## Consequences

- Zero-credential local development and CI.
- Stooq is unofficial and its history/adjustments have gaps; the ingestion
  validator flags anomalies, and switching to Tiingo/other is a drop-in.
- The provider contract is deliberately minimal so alternatives are easy to
  conform to.

## Alternatives considered

- **yfinance** - rejected as system of record: unofficial, fragile, known
  adjustment bugs; may be added later as a fallback provider.
- **Tiingo / Alpha Vantage / FMP free tier** - viable, deferred: require key
  management and have tighter rate limits; first target if Stooq quality bites.
