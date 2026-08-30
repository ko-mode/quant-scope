# 20. Thin cross-platform task runner (`justfile`)

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

Common developer operations span two toolchains (`uv` for the backend, `pnpm`
for the frontend) and Docker. Contributors need one obvious entry point, but the
canonical commands must stay visible and not be hidden behind opaque scripting.

## Decision

Add a root `justfile` with **thin** recipes that only delegate to the underlying
commands. It pins the shell to `bash` on every platform
(`set shell` / `set windows-shell`) for consistent behaviour (Git for Windows
provides `bash`).

Phase 0 recipes:

| Recipe            | Delegates to                                                   |
|-------------------|---------------------------------------------------------------|
| `just dev`        | `docker compose up --build`                                    |
| `just test`       | backend `uv run pytest`                                        |
| `just lint`       | backend `ruff check` + `ruff format --check`; frontend `pnpm lint` |
| `just typecheck`  | backend `uv run mypy`; frontend `pnpm typecheck`              |
| `just import-boundaries` | backend `uv run lint-imports`                          |
| `just migrate`    | backend `uv run alembic upgrade head` (added in Phase 1A)     |
| `just db-check`   | backend `uv run alembic check` - models vs migrations (Phase 1A) |
| `just seed *ARGS` | backend `uv run quantscope seed-securities` (added in Phase 1B) |
| `just check`      | `lint` + `typecheck` + `import-boundaries` + `test` + frontend `pnpm build` |
| `just compose-config` | `docker compose config`                                  |

`README.md` retains every raw command as the source of truth. The `justfile`
must not grow logic beyond delegation.

`just ingest-demo` (price data for the demo tickers) is added in Phase 1C, once
that CLI command exists - not before.

## Consequences

- One memorable command set; `just check` mirrors CI locally.
- Contributors without `just` lose nothing - the README commands are complete.
- Recipes stay auditable at a glance.

## Alternatives considered

- **Makefile** - rejected: poor Windows support, tab sensitivity.
- **nox / tox** - rejected: Python-only, heavier, wrong tool for the JS side and
  Docker.
- **Root `package.json` scripts** - rejected: awkward home for Python/Docker
  tasks.
