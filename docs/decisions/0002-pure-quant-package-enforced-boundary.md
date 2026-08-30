# 2. Pure `quant` package with a CI-enforced import boundary

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

The platform's value depends on financial calculations being deterministic,
reproducible and testable in isolation. If analytics code can reach into the
database, HTTP layer or configuration, that guarantee erodes and unit tests grow
slow and brittle.

## Decision

`quantscope.quant` is a pure library: deterministic functions over pandas/numpy
objects, no I/O (network, filesystem, database, clock).

**Allowed imports (the complete list):** the Python standard library, `numpy`,
`pandas`, `scipy`, `statsmodels`, `pandera`.

**Forbidden imports:** `quantscope.api`, `quantscope.services`,
`quantscope.data`, `quantscope.db`, `quantscope.config`, `quantscope.main`;
`fastapi` / `starlette`; `sqlalchemy` / `alembic`; `httpx`; database drivers
(`psycopg`); `pydantic` / `pydantic_settings`; and any market-data / vendor SDK.

The boundary is enforced by an `import-linter` *forbidden* contract in
`backend/pyproject.toml` (with `include_external_packages = true`), run in CI and
in pre-commit. The contract enumerates every application package plus the web /
DB / HTTP / vendor libraries above, so anything outside the allowed list is
rejected. A fast `pytest` smoke test (`tests/unit/quant/test_boundary.py`)
provides a second signal.

The service layer owns everything the engine excludes: loading data, converting
to/from wire schemas, attaching the `assumptions` block, and error handling.

## Consequences

- Analytics tests run without a database or network and can assert exact
  golden values.
- A future backtesting engine and AI tool layer consume the same pure functions.
- Contributors occasionally have to move glue code out of `quant` when the linter
  rejects it - this is the intended friction.

## Alternatives considered

- **Convention only (no enforcement)** - rejected: boundaries without CI checks
  rot within weeks.
- **Separate installable package/repo for `quant`** - deferred: same isolation
  benefit is available in-repo via the linter, without the packaging overhead.
