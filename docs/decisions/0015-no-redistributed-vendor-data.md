# 15. No redistributed vendor data in the repository

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

The project is a public CV repository. Free market-data and factor sources
(Stooq, Ken French) have terms that do not grant redistribution rights; SEC
data is public domain but bulk-committing extracts still bloats history and
blurs the line between "our code" and "their data". "Reproducible demo" must not
be read as "commit the datasets".

## Decision

The public repository **must not contain redistributed raw external financial
datasets** unless a dataset's licence explicitly permits redistribution.

The repository **does** contain:

- ingestion code and the provider abstraction;
- database and Pandera schemas;
- **synthetic** test fixtures;
- **manually constructed** golden-value datasets - small return series with
  analytically known results, plus a few hand-entered `(date, value)` reference
  points for the demo names;
- documented commands for fetching external data into a local database.

Demo reproducibility = **reproducible ingestion + methodology**. The six demo
securities (NVDA, AMD, INTC, AAPL, MSFT, SPY) are populated by a Phase 1
`just ingest-demo` command that calls the provider on the developer's machine.
Search still covers the broader SEC-seeded universe.

The market-data provider is treated as **replaceable**, not authoritative:
vendor quirks live only in the `PriceProvider` implementation.

**Phase 1 spot-check.** Ingestion for the demo securities is validated against a
small hand-authored expected-behaviour fixture, explicitly covering **NVDA's
10-for-1 split (ex-date 2024-06-10)**: no ~10x discontinuity in `adj_close`
across the split, consistent back-adjustment of pre-split bars, and a few
manually transcribed reference points matching within tolerance.

## Consequences

- No licensing exposure from redistributing third-party data; smaller repo.
- Tests that need real numbers rely on hand-verified constants, which is also
  better test design.
- A fresh clone needs network + a documented `ingest` step before the dashboard
  shows real data; CI exercises analytics against synthetic/golden fixtures.

## Alternatives considered

- **Commit a small Parquet snapshot for the demo** - rejected: still
  redistribution; still drifts from "reproducible via ingestion".
- **Git LFS for datasets** - rejected: same licensing problem, plus LFS setup.
