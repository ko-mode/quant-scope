# 3. Provider abstraction + ingestion separate from analytics

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

V1 uses free data sources that are unofficial, rate-limited and occasionally
wrong. The analytics engine must not be coupled to any of them, and a flaky
upstream must not make a research request fail or non-deterministic.

## Decision

- External sources sit behind narrow `Protocol` interfaces in
  `quantscope.data.providers` (`PriceProvider`, `FundamentalsProvider`,
  `FactorProvider`). One implementation each for V1.
- A separate ingestion pipeline (`fetch -> validate -> normalise -> upsert`),
  invoked by CLI/scheduled jobs, is the only thing that talks to providers.
- The request path reads exclusively from PostgreSQL. Missing or stale data
  yields an explicit error telling the operator to run ingestion - never a live
  fetch inside the request.
- Every ingestion invocation writes a `data_ingestion_run` audit row.

## Consequences

- Swapping Stooq for Tiingo (or adding a paid vendor) is a new class + config
  change; no analytics code moves.
- Requests are fast and reproducible; the same request returns the same numbers.
- A background freshness job is needed eventually; until then ingestion is a
  manual/cron CLI step, which is acceptable for the MVP.

## Alternatives considered

- **Fetch-through cache in the request path** - rejected: couples request
  latency and success to upstream availability, and undermines reproducibility.
- **ORM-specific provider interfaces** - rejected: providers should return plain
  validated frames/DTOs, not ORM objects.
