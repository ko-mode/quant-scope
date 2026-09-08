# QuantScope

A quantitative equity research platform: search a US equity, ingest and store
its market data, and compute deterministic performance, risk and factor
analytics behind a polished research dashboard.

> **Status: Phases 0-3B complete (MVP scope = Phases 0-3).**
> Phase 1 (DB, SEC seeding, Tiingo price provider + Pandera validation,
> validated persistence, the read-only `GET /securities[...]` API, and the
> frontend search → ticker page → adjusted-price chart) is complete. Phase 2
> (the pure `quantscope.quant` engine, `GET /securities/{ticker}/analytics`,
> and Kenneth French daily factor + RF ingestion wiring Sharpe and CAPM beta
> to real risk-free data) is complete. Phase 3A (`GET /compare`, multi-security
> comparison) and Phase 3B (`GET /securities/{ticker}/factors`, SPY CAPM +
> Fama-French 3-factor regression with Newey-West/HAC inference) are complete.
> Remaining Phase 3 scope is SEC EDGAR fundamentals ingestion and the
> canonical-metric mapping layer - not yet started, and not required for the
> analytics already shipped.
> See [`docs/architecture.md`](docs/architecture.md) §10 for the roadmap and
> [`docs/decisions/`](docs/decisions/) for the decision records (ADRs 0001-0023).

---

## Repository layout

```
quant-scope/
├── backend/            FastAPI + SQLAlchemy + Alembic (Python, uv)
│   ├── src/quantscope/
│   │   ├── api/        HTTP layer: routers (health, securities, analytics,
│   │   │               compare, factors) + schemas
│   │   ├── quant/      PURE analytics library (stdlib + numpy/pandas/scipy/
│   │   │               statsmodels/pandera only; boundary enforced in CI)
│   │   ├── data/       providers, ingestion, validation, XNYS calendar
│   │   ├── services/   orchestration: services.{analytics,comparison,factors}
│   │   ├── db/         SQLAlchemy base + session + ORM models (security,
│   │   │               price_bar, factor_return, data_ingestion_run) +
│   │   │               repositories
│   │   ├── config.py   pydantic-settings
│   │   └── main.py     application factory
│   ├── alembic/        migration env + migrations 0001-0003
│   └── tests/          pytest (unit/ + integration/)
├── frontend/           Next.js (App Router) + TypeScript + TanStack Query
│   └── src/
│       ├── app/        layout, providers (QueryClient), landing page
│       ├── components/ Price / Risk & Return / Comparison / Factors tab panels
│       └── lib/api/    typed fetch client
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
| `just ingest-factors *ARGS` | backend `quantscope ingest-factors` (Kenneth French daily FF3 + RF)     |
| `just check`             | `lint` + `typecheck` + `import-boundaries` + `test` + frontend `pnpm test` + frontend `pnpm build` |
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

### Factor ingestion (Phase 2B.1)

Fetch → parse → normalise → Pandera-validate → persist the Kenneth French
**daily Fama/French 3 factors + RF** (`Mkt-RF`, `SMB`, `HML`, `RF`) into
`factor_return`. This is what powers Sharpe and CAPM beta in the analytics API
below; requires the migration applied (no security dependency - factors are
market-wide, not tied to the seeded universe).

```bash
export QUANTSCOPE_DATABASE_URL=postgresql+psycopg://quantscope:quantscope@localhost:5432/quantscope

uv run quantscope ingest-factors                                    # or: just ingest-factors
uv run quantscope ingest-factors --start 2015-01-01 --end 2025-01-31 # trim the persisted window
uv run quantscope ingest-factors --dry-run                          # fetch+validate only, no writes, no run row
uv run quantscope ingest-factors --source-file ff3_daily.zip        # offline: a local ZIP or CSV copy
```

The Ken French file is not date-filterable at the source, so it is always
fetched whole (~26k trading dates × 4 factors) and `--start`/`--end` trim the
*persisted* window afterwards. One run, one `data_ingestion_run` row
(`entity='factors'`, `source='kenneth_french'`). Stored `value` is a **decimal
daily return** — the source's percent is divided by 100 before persistence
(`0.25` → `0.0025`), so never treat a `factor_return.value` as a percentage.
Persistence is idempotent on `(factor_name, frequency, trade_date, source)`:
a re-run of unchanged data writes nothing; a changed value updates in place.
A malformed row (bad date, unparseable number, an unsupported factor name, a
Kenneth French missing-value sentinel, or a value implausible for a decimal
daily return — `abs(value) >= 0.5`, a percent-vs-decimal-confusion tripwire,
not an economic cap) is dropped with a structured reason, never guessed or
coerced.

### Analytics API (Phase 2B / 2B.1)

`GET /securities/{ticker}/analytics?start=&end=&source=` exposes the pure
`quantscope.quant` engine over persisted price and factor history.

| Aspect | Behaviour |
|---|---|
| Input | One price `source`'s **adjusted-close** bars for the window (defaults to `QUANTSCOPE_PRICE_PROVIDER`; sources are never merged; no raw-close fallback). `source` only accepts `tiingo` here — Stooq's unverified adjustment is rejected with **422**, whether passed explicitly or only reachable via a `QUANTSCOPE_PRICE_PROVIDER=stooq` default (ADR 0022; QS-06 / RA-02). `start`/`end` are inclusive ISO dates, both optional; omitted ⇒ all persisted history. `start > end` → **422**. Unknown ticker → **404**. |
| Metrics | `return_summary`, `volatility`, `drawdown` (summary fields only), `var_es_95`, `var_es_99`. Each carries a `status`: `ok` \| `insufficient_observations` (below the ADR 0017 gate — 60 for return/vol/drawdown, 126 for VaR/ES) \| `undefined` \| `unavailable`. One suppressed metric never fails the response; a security with `< 2` bars returns **200** with everything suppressed. |
| Sharpe & beta | Read the persisted Kenneth French daily `RF` (`_load_daily_risk_free`); beta additionally loads SPY (same price source) and lets the engine align asset / SPY / RF. `status` is `ok` once RF (and, for beta, SPY) is present with enough overlap; `insufficient_observations` below the 126-observation gate; `undefined` for a zero-variance excess return (Sharpe) or zero-variance benchmark excess (beta) — a constant *asset* excess return still yields a valid beta/alpha with `r_squared: null`; `unavailable` (`reason`: `risk_free_series_not_ingested`, `benchmark_security_not_found`, or `benchmark_price_history_unavailable`) only when a required series isn't persisted at all. No constant/zero RF is ever substituted (ADR 0013). A beta failure never affects unrelated metrics. |
| Metadata | `price_observations`, `return_observations`, `analytics_start` / `analytics_end` (first/last **return** dates), and an `assumptions` block (ADR 0005): `annualisation_factor` 252, `calendar` XNYS, `return_type` total, `rf_source` (`kenneth_french_daily` or `not_ingested`) / `rf` (always `null` — RF is a time series, not one scalar) / `rf_basis` (`daily_series` or `null`), `benchmark` SPY, VaR horizon 1 / scaling none, `min_observations`, and a `suppressed` list. |
| Numbers | `float` end to end (the engine's precision) → JSON numbers; `null` for absent values; OpenAPI describes them as `number`, never `string`. |

```bash
curl -s "http://localhost:8000/securities/NVDA/analytics?source=tiingo"
curl -s "http://localhost:8000/securities/NVDA/analytics?start=2021-01-01&end=2023-12-31"
```

Analytics are deterministic: identical persisted inputs always yield identical
output, and no wall-clock time is read.

### Comparison API (Phase 3A)

`GET /compare?tickers=A,B,...&start=&end=&source=` compares 2-8 distinct
tickers on one common, N-way inner-joined return panel.

| Aspect | Behaviour |
|---|---|
| Input | `tickers` is a comma-separated list, normalised and de-duplicated, 2-8 distinct tickers required (**422** otherwise). Same `start`/`end`/`source` conventions as `/analytics`, including the `tiingo`-only `source` restriction (QS-06 / RA-02). Any unknown ticker → **404**. |
| Panel | Each ticker's own adjusted-close returns are computed independently, then joined into **one** inner-joined panel (never pairwise) - `observations_used`, `aligned_start`, `aligned_end` all describe that single panel. |
| Status | Flat top-level `status` (no nested `assumptions` block, unlike `/analytics`): `ok`; `insufficient_observations` (panel below `MIN_OBS_COMPARISON` = 60 - including when every persisted-history ticker's returns are entirely suppressed by a calendar gap, RA-03); `unavailable` (any ticker has fewer than 2 persisted bars at all, `unavailable_tickers` lists every offender). |
| Output | `normalized_performance` (base 100, every aligned return compounded, none divided away) and a Pearson `correlation` matrix, both `null` unless `status: "ok"`. A zero-variance ticker's correlation cells are `null`, listed in `zero_variance_tickers` - never coerced to `0`/`1`. |

```bash
curl -s "http://localhost:8000/compare?tickers=NVDA,AMD,INTC&source=tiingo"
```

### Factors API (Phase 3B)

`GET /securities/{ticker}/factors?start=&end=&source=` returns two regressions
together: the SPY CAPM regression and the Fama-French 3-factor (Mkt-RF/SMB/HML)
regression, both OLS with Newey-West (HAC) standard errors, t-stats, p-values
and 95% confidence intervals (ADR 0017 addendum, ADR 0023).

| Aspect | Behaviour |
|---|---|
| Input | Same `start`/`end`/`source` conventions as `/analytics`, including the `tiingo`-only `source` restriction (QS-06 / RA-02). Unknown ticker → **404**. |
| Models | `capm` (asset excess return vs SPY excess return - the same economic model as the Risk & Return tab's "Beta vs SPY", now with full inference) and `ff3` (asset excess return vs Ken French Mkt-RF/SMB/HML), returned together in one response - never split across two requests. **The SPY CAPM beta and the FF3 Mkt-RF coefficient are different quantities**, stated explicitly in `assumptions.capm_vs_ff3_note`. |
| Status | Each model has its own 4-valued `status`, independent of the other: `ok`; `insufficient_observations` (aligned panel below the model's gate - 126 for CAPM, 250 for FF3 - including zero valid returns from calendar-gap suppression despite persisted history existing, RA-03); `undefined` (a zero-variance regressor or a rank-deficient design, named in `reason`); `unavailable` (a required input - price history, RF, or a factor - was never ingested at all). |
| Coefficients | `alpha` first, then the regressor(s) in a fixed order. `alpha` is always the **daily** regression intercept - never annualised. `hac_lags` records the exact Newey-West lag used (`floor(4*(T/100)**(2/9))`, minimum 1), reproducible from `observations_used` alone. A coefficient's `std_error`/`t_stat`/`p_value`/`ci_low`/`ci_high` may individually be `null` even when the model's own `status` is `ok` (e.g. a HAC standard error that underflows to exactly 0) - `estimate` stays populated. |

```bash
curl -s "http://localhost:8000/securities/NVDA/factors?source=tiingo"
```

### Frontend (Phase 1F, extended through 3B)

```bash
cd frontend
pnpm install
pnpm dev                     # http://localhost:3000  (needs the backend on :8000)
```

A **landing search** (`GET /securities?q=`, debounced, keyboard-navigable) and
a **ticker page** at `/securities/{ticker}` (`GET /securities/{ticker}`;
unknown ticker → styled 404) with four tabs, one per backend endpoint added
since Phase 1F; Fundamentals is shown as a disabled "soon" tab, since it is
not built yet:

| Tab | Backed by | Notes |
|---|---|---|
| Price | `GET /securities/{ticker}/prices` | Plots `adj_close` (the V1 total-return series, ADR 0012) as a hand-drawn SVG line + area, `1Y/3Y/5Y/MAX` range controls, an optional dashed raw-`close` overlay, a crosshair tooltip, and the resolved `source` shown next to the chart. |
| Risk & Return | `GET /securities/{ticker}/analytics` | Return summary, volatility, Sharpe, max drawdown, beta vs SPY, historical VaR/ES - each rendered per its own `status`, never a fabricated number for a suppressed metric. |
| Comparison | `GET /compare` | A ticker-chip picker (2-8 securities), the normalized-performance chart, and a correlation table; `null` correlation cells render as `—`, never `0`/`1`. |
| Factors | `GET /securities/{ticker}/factors` | CAPM and FF3 coefficient tables shown simultaneously (factor / estimate / HAC SE / t-stat / p-value), with the mandatory SPY-vs-Mkt-RF disambiguation note - no chart. |

Every panel shows an explicit "Refreshing…" indicator while TanStack Query is
serving placeholder data for a newly selected ticker/range, so a previous
result is never mistaken for a confirmed one (QS-07). No analytics are
computed client-side; every number comes from the backend as-is.

Stack additions: `next/font` for Inter + IBM Plex Mono; hand-rolled SVG charts
(no charting dependency); Vitest + Testing Library for component/logic tests.
Light theme only.

Run against the backend with `NEXT_PUBLIC_API_BASE_URL` (default
`http://localhost:8000`). Running the backend outside Docker on Windows, bind
uvicorn to `127.0.0.1` **and** browse the frontend on `http://localhost:3000`
(the CORS allow-list origin); if the Next server can't reach the API, point
`NEXT_PUBLIC_API_BASE_URL` at `http://127.0.0.1:8000` (Node resolves `localhost`
to IPv6 first). The Docker Compose stack is unaffected.

Checks:

```bash
pnpm typecheck               # tsc --noEmit
pnpm lint                    # next lint
pnpm test                    # vitest run
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

No external datasets are committed to this repository (ADR 0015). The security
universe (from SEC reference data, not SEC *fundamentals* - see below), daily
prices, and Kenneth French daily factors are all fetched by local ingestion.
SEC EDGAR *fundamentals* (revenue, earnings, per-share metrics) are not
ingested by this MVP - see "What this MVP intentionally does not include yet"
below. Tests use synthetic fixtures and hand-built golden values. "Reproduce
the demo" means run the documented ingestion, not clone a dataset.

---

## What this MVP intentionally does **not** include yet

Fundamentals (SEC EDGAR ingestion + the canonical-metric mapping layer) is the
one piece of the original Phase 0-3 MVP scope not yet built; it is deferred,
not required for the analytics, comparison, and factor regression already
shipped. Portfolio analytics, backtesting, SEC filings browsing, the AI
assistant and its evaluation harness, authentication, Redis, and background
workers are all out of MVP scope entirely. These are supported by the
architecture but would be added in later phases - see `docs/architecture.md`
sections 9-10. No placeholder packages exist for them.
