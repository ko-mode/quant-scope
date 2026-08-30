# QuantScope

A quantitative equity research platform: search a US equity, ingest and store
its market data, and compute deterministic performance, risk and factor
analytics behind a polished research dashboard.

> **Status: Phase 0 (scaffold).** No feature functionality yet. This milestone
> establishes the repository structure, tooling, CI and a running skeleton.
> See [`docs/architecture.md`](docs/architecture.md) for the full plan and
> [`docs/decisions/`](docs/decisions/) for the decision records (ADRs 0001-0020).

---

## Repository layout

```
quant-scope/
├── backend/            FastAPI + SQLAlchemy + Alembic (Python, uv)
│   ├── src/quantscope/
│   │   ├── api/        HTTP layer (routers, schemas) - /health only for now
│   │   ├── quant/      PURE analytics library (stdlib + numpy/pandas/scipy/
│   │   │               statsmodels/pandera only; boundary enforced in CI)
│   │   ├── db/         SQLAlchemy base + session (no models yet)
│   │   ├── config.py   pydantic-settings
│   │   └── main.py     application factory
│   ├── alembic/        migration env (no migrations yet)
│   └── tests/          pytest (unit/ + integration/)
├── frontend/           Next.js (App Router) + TypeScript + TanStack Query
│   └── src/
│       ├── app/        layout, providers (QueryClient), landing page
│       └── lib/api/    typed fetch client (endpoints added in Phase 1)
├── docs/               architecture.md + decisions/ (ADRs)
├── .github/workflows/  CI (backend, frontend, compose validation)
├── docker-compose.yml  db + backend + frontend
├── justfile            thin task runner (see below)
└── .env.example
```

---

## Prerequisites

| Tool           | Version         | Notes                                             |
|----------------|-----------------|--------------------------------------------------|
| Docker + Compose | 24+ / v2+     | For the one-command stack.                        |
| Python         | 3.11+           | Only needed to run the backend outside Docker.    |
| [uv](https://docs.astral.sh/uv/) | 0.12+ | Backend dependency manager. `pip install uv`.    |
| Node.js        | 20.11+ (22 LTS) | Only needed to run the frontend outside Docker.   |
| [pnpm](https://pnpm.io/) | 9.15  | `npm install -g pnpm@9.15.0` or `corepack enable`.|
| [just](https://github.com/casey/just) | 1.x | Optional task runner. On Windows it uses `bash` from Git for Windows. |

---

## Task runner (`just`)

Optional convenience wrappers (ADR 0020). Every underlying command is also listed
below and remains the source of truth.

| Command                  | Does                                                        |
|--------------------------|-----------------------------------------------------------|
| `just dev`               | `docker compose up --build` - the full local stack          |
| `just test`              | backend `pytest`                                            |
| `just lint`              | backend `ruff check` + `ruff format --check`; frontend `pnpm lint` |
| `just typecheck`         | backend `mypy`; frontend `pnpm typecheck`                  |
| `just import-boundaries` | backend `lint-imports` (quant dependency contract)          |
| `just migrate`           | backend `alembic upgrade head`                              |
| `just db-check`          | backend `alembic check` (models vs migrations)              |
| `just check`             | `lint` + `typecheck` + `import-boundaries` + `test` + frontend `pnpm build` |
| `just compose-config`    | `docker compose config` (no daemon needed)                  |

`just seed` and `just ingest-demo` are added in Phase 1B, once those CLI commands
exist.

---

## Quick start (Docker - recommended)

```bash
cp .env.example .env
docker compose up --build      # or: just dev
```

Then:

| Service            | URL                                  |
|--------------------|--------------------------------------|
| Backend health     | http://localhost:8000/health         |
| API docs (Swagger) | http://localhost:8000/docs           |
| Frontend           | http://localhost:3000                |
| PostgreSQL         | `localhost:5432` (user/pass/db `quantscope`) |

**Verify `/health`:**

```bash
curl -s http://localhost:8000/health
# {"status":"ok","service":"quantscope-api","version":"0.1.0"}
```

Stop with `Ctrl+C`; `docker compose down` to remove containers (add `-v` to drop
the database volume).

---

## Local development (without Docker)

### Backend

```bash
cd backend
uv sync                                   # create .venv, install deps + dev tools
cp ../.env.example .env                    # or export QUANTSCOPE_* vars
uv run uvicorn quantscope.main:app --reload --port 8000
curl -s http://localhost:8000/health
```

A database is **not** required for `/health`. Most of the test suite also runs
without one; the database-backed schema tests are skipped unless
`QUANTSCOPE_TEST_DATABASE_URL` points at a **disposable** PostgreSQL database.

Checks (all run in CI):

```bash
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run mypy                  # type check (strict on quantscope.quant)
uv run lint-imports          # enforce the quant dependency contract
uv run pytest                # tests (DB schema tests skipped without QUANTSCOPE_TEST_DATABASE_URL)
uv run alembic history       # migration history
```

Run the migration and the model/migration drift check against a database:

```bash
export QUANTSCOPE_DATABASE_URL=postgresql+psycopg://quantscope:quantscope@localhost:5432/quantscope
uv run alembic upgrade head       # or: just migrate
uv run alembic check              # or: just db-check  -> "No new upgrade operations detected."
```

### Frontend

```bash
cd frontend
pnpm install
pnpm dev                     # http://localhost:3000
```

Checks:

```bash
pnpm typecheck               # tsc --noEmit
pnpm lint                    # next lint
pnpm build                   # production build
```

### pre-commit (optional but recommended)

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

Requires `uv` on PATH (backend hooks run via `uv run --directory backend ...`).

---

## Environment variables

Copy `.env.example` to `.env`. Backend variables use the `QUANTSCOPE_` prefix
and have development defaults, so the app starts without a `.env` file. Compose
injects `QUANTSCOPE_DATABASE_URL` pointing at the `db` service; outside Compose
the default points at `localhost:5432`.

---

## Data

No external datasets are committed to this repository (ADR 0015). Prices, SEC
fundamentals and Fama-French factors are fetched by local ingestion (added in
Phase 1). Tests use synthetic fixtures and hand-built golden values. "Reproduce
the demo" means run the documented ingestion, not clone a dataset.

---

## What Phase 0 intentionally does **not** include

Portfolio analytics, backtesting, SEC filings, the AI assistant and its
evaluation harness, authentication, Redis, and background workers. These are
supported by the architecture but are added in later phases - see
`docs/architecture.md` sections 9-10. No placeholder packages exist for them.
