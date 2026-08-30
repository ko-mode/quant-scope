# 7. No auth, Redis, queue or workers in V1

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

The MVP (Phases 0-3) has no user-scoped data and no long-running jobs.
Ingestion is a CLI step; analytics compute on daily data is sub-second.

## Decision

Do not add authentication/authorisation, Redis, a task queue (Celery/RQ/Arq),
or background workers. Do not add `owner_id` columns. `docker-compose` runs
exactly three services: `db`, `backend`, `frontend`.

Revisit when a phase creates the need:

- Backtesting (Phase 5) introduces genuinely long CPU jobs -> add a queue +
  worker + Redis then.
- Portfolios (Phase 4) or any multi-user requirement -> add auth and `owner_id`
  then, as an additive migration.

## Consequences

- Minimal moving parts; fast local setup; CI stays simple.
- No request authentication - acceptable for local/single-operator use; must be
  addressed before any shared deployment.
- Some rework when infra is added later, but against a known, bounded surface.

## Alternatives considered

- **Add JWT auth "to be safe"** - rejected: unused complexity, and a security
  surface with no users to protect.
- **Redis for caching now** - rejected: no measured need; in-process caching
  suffices if profiling later shows one.
