# 14. Python tooling: uv, Ruff, mypy, pytest, import-linter

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

A correctness-critical codebase needs fast, deterministic dependency management
and strong static guardrails, consistent between local development and CI.

## Decision

- **uv** for environment and dependency management. Dependencies and dev group
  in `backend/pyproject.toml` (PEP 621 + PEP 735); `uv.lock` committed; CI runs
  `uv sync --frozen`.
- **Ruff** for linting and formatting (single tool, replaces flake8/isort/black).
- **mypy** with a strict baseline everywhere and the strictest settings on
  `quantscope.quant.*`.
- **pytest** for tests; provider interactions use recorded cassettes, with a
  separate nightly live contract suite.
- **import-linter** (`lint-imports`) enforces the ADR 0002 boundary.
- **pre-commit** runs Ruff, mypy and import-linter on staged changes.
- Python **3.11+**; `src/` layout; package `quantscope`.

Frontend counterpart: **pnpm** (pinned via `packageManager`), `tsc --noEmit`,
`next lint` (ESLint flat config), `next build`.

## Consequences

- Sub-second installs, reproducible resolution, identical checks locally and in
  CI.
- Contributors need `uv` and `pnpm` on PATH (documented in the root README).
- Ruff/mypy strictness occasionally requires up-front type work - the intended
  trade for a reliable analytics core.

## Alternatives considered

- **Poetry / pip-tools** - rejected: slower; uv covers the same ground with a
  better lockfile story.
- **black + flake8 + isort** - rejected: three tools where Ruff is one.
