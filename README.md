# QuantScope

A quantitative equity research platform: search a US equity, ingest and store
its market data, and compute deterministic performance, risk and factor
analytics behind a polished research dashboard.

> **Status: Phase 1 (search + market-data ingestion), in sub-phases.**
> 1A (DB models/migration), 1B (SEC security-universe seeding), 1C
> (price-provider contract + normalisation + Pandera validation + NVDA split
> spot-check), 1C.1 (Tiingo adapter, ADR 0022) and 1D (validated price
> persistence + `ingest-prices` / `just ingest-demo`) are complete; 1E
> (read-only `GET /securities`, `/securities/{ticker}`,
> `/securities/{ticker}/prices`) is in review. No frontend features yet.
> See [`docs/architecture.md`](docs/architecture.md) §10 for the roadmap and
> [`docs/decisions/`](docs/decisions/) for the decision records (ADRs 0001-0022).

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
| `just seed *ARGS`        | backend `quantscope seed-securities` (security universe from SEC) |
| `just ingest-prices TICKER *ARGS` | backend `quantscope ingest-prices` for one seeded ticker |
| `just ingest-demo *ARGS` | ingest ~20y of daily prices for the six demo tickers (NVDA AMD INTC AAPL MSFT SPY) |
| `just check`             | `lint` + `typecheck` + `import-boundaries` + `test` + frontend `pnpm build` |
| `just compose-config`    | `docker compose config` (no daemon needed)                  |

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

### Seed the security universe (Phase 1B)

Populates the `security` table from SEC reference data
(`company_tickers_exchange.json`). Requires the migration to have been applied.

```bash
export QUANTSCOPE_DATABASE_URL=postgresql+psycopg://quantscope:quantscope@localhost:5432/quantscope
export QUANTSCOPE_SEC_USER_AGENT="YourName your.email@example.com"   # SEC requires this

uv run quantscope seed-securities              # fetch from SEC        (or: just seed)
uv run quantscope seed-securities --dry-run    # fetch + normalise, write nothing
```

The dataset is never committed (ADR 0015). To work offline, download the file
once and pass it in:

```bash
curl -A "$QUANTSCOPE_SEC_USER_AGENT" -o sec.json \
  https://www.sec.gov/files/company_tickers_exchange.json
uv run quantscope seed-securities --source-file sec.json   # or: just seed -- --source-file sec.json
```

Re-running the seed is idempotent: unchanged rows are untouched, `security.id`
values are stable, and rows that vanish from a later SEC snapshot are **not**
deleted or deactivated. Each run is logged as JSON lines and recorded in
`data_ingestion_run`.

V1 scope (ADR 0021): **exchange-listed US securities only** - OTC records are
rejected with reason `unsupported_exchange_v1:OTC`. `security.exchange` is a
MIC-style code **normalised from the single SEC exchange label**; it is not
cross-verified listing-venue metadata and may differ from a security's true
primary listing (e.g. SEC labels `SPY` "NYSE").

### Daily-price provider: Tiingo (Phase 1C)

Tiingo is QuantScope's V1 live daily-price provider (ADR 0022). A **free** token
is required for any live fetch; **never commit it**.

1. Sign up at <https://www.tiingo.com> (free) and copy your token from
   <https://www.tiingo.com/account/api/token>.
2. `export QUANTSCOPE_TIINGO_TOKEN=<your token>` (or put it in `.env`).

Tiingo returns raw OHLCV **and** a CRSP split-and-dividend–adjusted close
(`adjClose` → our `adj_close`), plus `divCash` / `splitFactor`. The adapter maps
its JSON into the existing `RawPriceBar` → `normalize_price_bars` → Pandera
validation pipeline unchanged. Fetched observations are for internal/local use
only and are never committed or redistributed (ADR 0015). Free-tier limits (as
of 2026-08-31): 50 req/hr, 1000 req/day, 500 symbols/month, 1 GB/month.

The **Stooq** adapter (`quantscope.data.providers.stooq`) is retained as a
second `DailyPriceProvider` implementation and offline CSV parser; its live
endpoint is anti-bot gated and cannot be used for automated ingestion (ADR 0022).

Guarded live smoke tests in `backend/tests/integration/live/` run only when
`QUANTSCOPE_TIINGO_TOKEN` is set.

### Ingest daily prices (Phase 1D)

Fetch → normalise → Pandera-validate → persist one **already-seeded** ticker's
daily bars into `price_bar`. Requires the migration applied and the security
universe seeded; ingestion never creates `security` rows.

```bash
export QUANTSCOPE_DATABASE_URL=postgresql+psycopg://quantscope:quantscope@localhost:5432/quantscope
export QUANTSCOPE_TIINGO_TOKEN=<your token>          # provider default is Tiingo (ADR 0022)

uv run quantscope ingest-prices NVDA --start 2015-01-01 --end 2025-01-31
uv run quantscope ingest-prices NVDA --start 2015-01-01                 # --end defaults to today
uv run quantscope ingest-prices NVDA --start 2015-01-01 --dry-run       # fetch+validate only, no writes, no run row
uv run quantscope ingest-prices NVDA --start 2015-01-01 --provider stooq
just ingest-demo                                                        # all six demo tickers, 2005-01-01..today
```

Each ticker is one transaction and one `data_ingestion_run` row (`entity='prices'`):
`success` (all bars valid), `partial` (some/all bars dropped by normalisation or
Pandera - reasons are logged and counted), or `failed` (provider/network/auth
error, unknown ticker, or a DB error - nothing is persisted). Persistence is
idempotent on the composite identity `(security_id, trade_date, source)`: a
re-run of unchanged data writes nothing and leaves the row count stable; changed
vendor values update in place; a second `source` for the same security/date
coexists rather than overwriting. The command prints a one-line JSON summary
(`inserted` / `updated` / `unchanged` / `rows_written` / `status`).

`just ingest-demo` uses **2005-01-01 → today** for all six demo tickers: it
covers their full free-tier history, spans several market regimes for later
beta / multi-year volatility / factor regressions, and costs just six API
requests. Fetched observations are for internal/local use only and are never
committed (ADR 0015). Phase 1D adds no migration and no API.

### Read-only API (Phase 1E)

Three GET routes over the seeded universe and the persisted price history.
Served at the root (like `/health`); browse the schema at `/docs`.

| Route | Notes |
|---|---|
| `GET /securities?q=&limit=&offset=` | Case-insensitive partial match on ticker **or** name (trigram-indexed). Exact ticker match sorts first, then `ticker` ascending. `limit` 1–200 (default 50). Inactive/delisted securities are included. Envelope: `{results, limit, offset, count}`. |
| `GET /securities/{ticker}` | Ticker resolved via the shared normaliser, so `nvda` == `NVDA`. Unknown ticker → **404** (no fuzzy fallback). |
| `GET /securities/{ticker}/prices?start=&end=&source=&limit=&offset=` | Persisted daily bars, `trade_date` ascending, from **one** `source`. `start`/`end` are inclusive ISO dates; `start > end` → **422**. `source` is `tiingo` or `stooq`; **when omitted it defaults to `QUANTSCOPE_PRICE_PROVIDER`** — series from different providers are never merged. `limit` 1–20000 (default 5000). A known security with no bars in range → **200** with an empty list. |

Prices are exact `NUMERIC(18, 6)` / `Decimal` in the database and the domain
layer; they are converted to `float` **only at the JSON boundary**, so the API
emits numbers (`"close": 100.1`) — the precision the quant engine already works
in, and directly usable by a charting frontend without a parse step. `count` is
the number of rows **in this page**, not a universe-wide match total (clients
detect "more" via `count == limit`). `security.id` and `price_bar.ingested_at`
are not exposed. No analytics are computed here.

```bash
curl -s "http://localhost:8000/securities?q=nvda"
curl -s "http://localhost:8000/securities/nvda"
curl -s "http://localhost:8000/securities/NVDA/prices?source=tiingo&start=2024-01-01&end=2024-12-31"
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
