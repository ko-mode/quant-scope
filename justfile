# QuantScope developer task runner (ADR 0020).
#
# Thin wrappers only - every underlying command is documented in README.md,
# which remains the source of truth. Requires: just, uv (backend),
# pnpm (frontend), docker (for `just dev` / `just compose-config`).
#
# Phase 1 will add `seed` and `ingest-demo` once those CLI commands exist.

set shell := ["bash", "-eu", "-o", "pipefail", "-c"]
set windows-shell := ["bash", "-eu", "-o", "pipefail", "-c"]

# Show available recipes
default:
    @just --list

# Run the full local stack (Postgres + backend + frontend) via Docker
dev:
    docker compose up --build

# Backend test suite
test:
    cd backend && uv run pytest

# Lint backend (ruff) and frontend (next lint)
lint:
    cd backend && uv run ruff check .
    cd backend && uv run ruff format --check .
    cd frontend && pnpm lint

# Type-check backend (mypy) and frontend (tsc)
typecheck:
    cd backend && uv run mypy
    cd frontend && pnpm typecheck

# Enforce the quant engine dependency contract
import-boundaries:
    cd backend && uv run lint-imports

# Everything CI runs except Docker image builds
check: lint typecheck import-boundaries test
    cd frontend && pnpm build

# Validate the docker compose configuration (no daemon needed)
compose-config:
    docker compose config --quiet && echo "docker-compose.yml: valid"
