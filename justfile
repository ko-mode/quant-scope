# QuantScope developer task runner (ADR 0020).
#
# Thin wrappers only - every underlying command is documented in README.md,
# which remains the source of truth. Requires: just, uv (backend),
# pnpm (frontend), docker (for `just dev` / `just compose-config`).
#
# `ingest-demo` (price data for the demo tickers) is added in Phase 1D.

set shell := ["bash", "-eu", "-o", "pipefail", "-c"]
set windows-shell := ["bash", "-eu", "-o", "pipefail", "-c"]

# Force UTF-8 for child processes: some tools (import-linter/rich) emit non-ASCII
# and crash when Windows hands them a cp1252 stdout.
export PYTHONUTF8 := "1"
export PYTHONIOENCODING := "utf-8"

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

# Apply database migrations (uses QUANTSCOPE_DATABASE_URL / its dev default)
migrate:
    cd backend && uv run alembic upgrade head

# Fail if the models have drifted from the migrations
db-check:
    cd backend && uv run alembic check

# Seed the security universe from SEC reference data.
# Needs network; or pass a local file: `just seed -- --source-file path/to.json`.
seed *ARGS:
    cd backend && uv run quantscope seed-securities {{ARGS}}

# Ingest daily prices for one ticker (must be seeded). Uses QUANTSCOPE_PRICE_PROVIDER.
# e.g. `just ingest-prices NVDA -- --start 2015-01-01 --end 2025-01-31`
ingest-prices TICKER *ARGS:
    cd backend && uv run quantscope ingest-prices {{TICKER}} {{ARGS}}

# Ingest ~20y of daily prices for the six demo securities via the configured
# provider. Range 2005-01-01..today: covers every demo ticker's full free-tier
# history, spans multiple market regimes for later beta / 3-5y vol / factor
# regressions, and is just 6 API requests total. A single ticker failing does
# not abort the batch; the recipe still exits non-zero if any did.
ingest-demo *ARGS:
    cd backend && rc=0; for t in NVDA AMD INTC AAPL MSFT SPY; do \
        uv run quantscope ingest-prices "$t" --start 2005-01-01 {{ARGS}} || rc=1; \
    done; exit $rc

# Ingest the Kenneth French daily Fama/French 3 factors + RF into `factor_return`.
# One HTTP fetch of the whole history; idempotent. `just ingest-factors -- --start 2005-01-01`
# to trim, or `-- --source-file path/to.zip` for an offline copy.
ingest-factors *ARGS:
    cd backend && uv run quantscope ingest-factors {{ARGS}}

# Everything CI runs except Docker image builds
check: lint typecheck import-boundaries test
    cd frontend && pnpm test
    cd frontend && pnpm build

# Validate the docker compose configuration (no daemon needed)
compose-config:
    docker compose config --quiet && echo "docker-compose.yml: valid"
