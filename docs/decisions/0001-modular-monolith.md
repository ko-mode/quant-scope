# 1. Modular monolith, not microservices

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

QuantScope spans market data, analytics, portfolio tools, backtesting, filings
and an AI layer. That breadth invites premature decomposition into services. The
team is small and correctness/iteration speed matter more than independent
scaling.

## Decision

Build a single deployable FastAPI backend organised as internal packages with
enforced dependency direction (`api -> services -> quant/data -> db`). One
PostgreSQL database. The frontend is a separate Next.js app only because it is a
different runtime, not a separate service tier.

## Consequences

- One process to run, test, debug and deploy; transactional consistency is free.
- Module boundaries are enforced in code (`import-linter`) rather than by network
  calls, so they can be refined cheaply as understanding improves.
- If a component ever needs independent scaling (e.g. a backtest worker), it can
  be extracted later behind its already-existing package boundary.

## Alternatives considered

- **Microservices from the start** - rejected: operational overhead, distributed
  failure modes and schema coordination with no offsetting benefit at this size.
- **Serverless functions** - rejected: analytics need warm numeric libraries and
  shared data access; cold starts and fragmentation hurt.
