# QuantScope - Architecture

**Status:** approved for implementation (MVP scope = Phases 0-3)
**Last updated:** 2026-08-30 - Phase 0 review (provenance, fundamentals mapping,
quant conventions, dependency contract, DataFrame contracts, product priorities,
task runner); Phase 1A-1D in progress (ADRs 0021-0022; Phase 1 split into
sub-phases 1A-1F)

QuantScope is a quantitative equity research platform. This document describes
the architecture that has been approved for the initial, CV-ready product
milestone (Phases 0-3) and the boundaries that keep later phases (portfolio
analytics, backtesting, filings, AI, AI evaluation) reachable without a rewrite.

Decision records for the individual choices below live in
[`docs/decisions/`](./decisions/).

---

## 1. Guiding principles

1. **Correctness first.** Financial calculations are deterministic, reproducible
   and unit-tested against independently computed golden values.
2. **The quant engine is a pure library.** `quantscope.quant` performs no I/O and
   imports no framework or application infrastructure. It is the testable core;
   everything else is plumbing. The boundary is enforced in CI by `import-linter`
   (ADR 0002).
3. **Data providers are replaceable, not authoritative.** External APIs sit
   behind a narrow `Protocol`. Ingestion (fetch -> validate -> normalise ->
   persist) is a separate pipeline; the analytics path only ever reads from our
   database (ADR 0003).
4. **Provenance is captured from day one.** Every externally sourced row records
   `source` and `ingested_at`; fundamentals also record `filed_date` and
   `accession_no`. These cannot be backfilled later (ADR 0004).
5. **No redistributed vendor data in the repo.** The repository holds ingestion
   code, schemas, synthetic fixtures, hand-built golden-value data and fetch
   instructions - never bulk provider datasets. Reproducibility means
   reproducible ingestion and methodology (ADR 0015).
6. **Results are self-describing.** Every analytics response carries an
   `assumptions` block (window, calendar, annualisation factor, risk-free
   source, return type, market proxy, confidence levels, observation counts and
   any suppression reasons) so any number can be reproduced and audited
   (ADR 0005, ADR 0017).
7. **Modular monolith.** One deployable backend, one database. No microservices,
   no message broker, no workers until a phase genuinely needs them (ADR 0001,
   ADR 0007).
8. **No speculative abstraction.** Build for the current phase; keep seams where
   the next phase will attach.

**Priority order** (used to break ties in scope and effort - ADR 0019). The
primary audience is a technical hiring manager evaluating a CV project:

1. Quantitative correctness
2. Architectural clarity and ADR quality
3. Polished research dashboard
4. Reproducible local setup
5. Comparison and Fama-French 3-factor methodology
6. Feature breadth

---

## 2. System context

```
                +-------------------------------+
   Browser  --> |  Next.js frontend (App Router) |
                |  TanStack Query data layer     |
                +---------------+---------------+
                                | HTTPS / JSON
                                v
                +-------------------------------+
                |  FastAPI backend (modular      |
                |  monolith)                     |
                |                                |
                |  api -> services -> quant      |
                |                  \-> data      |
                |         repositories -> ORM    |
                +---------------+---------------+
                                | SQLAlchemy
                                v
                        +---------------+
                        |  PostgreSQL   |
                        +---------------+

   Ingestion (CLI / scheduled job, NOT in the request path):
     provider (Tiingo prices / SEC EDGAR / Ken French)
       -> validation (Pandera schema + sanity rules)
       -> normalisation (XNYS calendar; vendor-adjusted close; spot-checks)
       -> repository upsert -> PostgreSQL
```

External data sources for the MVP. All are fetched by local ingestion; none are
committed to the repository (see §3).

| Concern        | Source (V1)                       | Notes                                  |
|----------------|-----------------------------------|----------------------------------------|
| Daily prices   | **Tiingo** (Stooq retained)       | V1 live provider; raw close + CRSP split&dividend `adjClose`; free token. Stooq adapter kept but anti-bot blocked (ADR 0008, 0022) |
| Fundamentals   | SEC EDGAR CompanyFacts API        | Public domain; carries `filed_date` / `accession_no` |
| Factor returns | Ken French data library (daily)   | Mkt-RF, SMB, HML, **RF** (ADR 0009); usage terms - not redistributed |
| Security list  | SEC `company_tickers_exchange`    | Seeds the searchable universe          |
| Risk-free rate | Ken French `RF` series            | No separate table in V1 (ADR 0013)     |

---

## 3. Data provenance and redistribution

Locked in [ADR 0015](./decisions/0015-no-redistributed-vendor-data.md).

* **The public repository must not contain redistributed raw external financial
  datasets** unless a dataset's licence explicitly permits redistribution.
* The repository **does** contain: ingestion code; database and Pandera schemas;
  **synthetic** test fixtures; **manually constructed** golden-value datasets
  (small return series with analytically known answers, plus a few hand-entered
  `(date, value)` reference points for the demo names); and documented commands
  for fetching external data into a local database.
* **Demo reproducibility = reproducible ingestion + methodology.** The six demo
  securities (NVDA, AMD, INTC, AAPL, MSFT, SPY) are populated by
  `just ingest-demo` (a Phase 1D command), which calls the provider. Search
  still covers the broader universe seeded from the SEC ticker file (Phase 1B).
* The market-data provider is **replaceable**. Vendor quirks live only in the
  `DailyPriceProvider` implementation; no analytics code encodes a
  provider-specific assumption.
* **Corporate-action / adjusted-price spot-check (Phase 1C).** Provider output
  is checked against a small hand-authored expected-behaviour fixture, covering
  **NVDA's 10-for-1 split (ex-date 2024-06-10)**: the adjusted-close series must
  show no ~10x discontinuity across the split, and a few manually transcribed
  reference points must sit within tolerance of publicly-known post-split
  levels. The fixture is hand-written; it is not a vendor extract. It is a
  coarse "obviously broken?" check, not proof the vendor adjusted close is
  authoritative.

---

## 4. Backend layering

Outer layers depend inward only.

| Layer          | Package                        | Responsibility                                                                 |
|----------------|--------------------------------|-------------------------------------------------------------------------------|
| HTTP           | `quantscope.api`               | Routing, request/response Pydantic schemas, mapping domain errors to statuses. No logic. |
| Orchestration  | `quantscope.services`          | Use-cases: load data via repositories, call the engine, assemble the `assumptions` block, resolve canonical fundamentals metrics, manage transactions. |
| Analytics      | `quantscope.quant`             | Pure deterministic functions over pandas/numpy. Returns, risk, drawdown, performance, factor regression, correlation. |
| Ingestion      | `quantscope.data`              | `providers/` (Protocols + one impl each), `validation.py`, `ingest.py`, canonical-metric tag maps. Async HTTP allowed here only. |
| Persistence    | `quantscope.db`                | `base.py` (declarative base), `session.py`, `models/`, `repositories/`.       |
| Entrypoints    | `quantscope.main`, `jobs/` CLI | App factory; ingestion commands (`typer`).                                    |

### `quantscope.quant` dependency contract (ADR 0002)

`quantscope.quant` may import **only**:

* the Python standard library
* `numpy`, `pandas`, `scipy`, `statsmodels`, `pandera`

It must **not** import: `quantscope.api`, `quantscope.services`,
`quantscope.data`, `quantscope.db`, `quantscope.config`, `quantscope.main`;
`fastapi` / `starlette`; `sqlalchemy` / `alembic`; `httpx`; database drivers
(`psycopg`); `pydantic`; or any market-data / vendor SDK. Enforced by the
`import-linter` *forbidden* contract in `backend/pyproject.toml` and by a fast
`pytest` smoke test.

### DataFrame contracts (ADR 0018)

* Public `quant` functions take and return `pandas.Series` / `pandas.DataFrame`
  (and plain dataclasses for scalar result bundles).
* Canonical frame shapes (price panel, return panel, factor panel) are defined
  as **Pandera** schemas in `quantscope.quant.frames` and validated **at the
  public boundary** of the engine, not deep in the call stack.
* **No custom DataFrame wrapper classes** created solely to satisfy static
  typing.

### Analytics service flow (Phase 2B / 2B.1)

`GET /securities/{ticker}/analytics` is the first route with a real service
layer (`quantscope.services.analytics`). The flow is strictly one-directional:

```
router: resolve ticker (404) · reject start>end (422) · resolve source
   -> service:
        db.repositories.prices.get_all_price_bars(security, source, start, end)   # one source, ascending, unpaginated
        -> adjusted-close pandas.Series          # float(adj_close); raw close is never read (ADR 0012)
        -> quant.simple_returns(prices)          # called ONCE, reused
        -> quant.return_summary / annualised_volatility / drawdown_analysis /
           historical_var_es(0.95) / historical_var_es(0.99)
        -> _load_daily_risk_free(session, start, end)   # db.repositories.factors.get_factor_series(rf)
        -> quant.sharpe_ratio(returns, risk_free_daily=rf)
        -> [SPY security -> SPY price bars -> quant.simple_returns] -> quant.capm_beta(returns, spy_returns, rf)
        -> map each result dataclass -> its Pydantic metric model
        -> assemble the ADR 0005 `assumptions` block
```

Equivalently, the ingestion side that feeds `_load_daily_risk_free`:

```
Kenneth French daily FF3 (ZIP -> CSV)
      -> KennethFrenchDailyFactorProvider / parse_ff_daily_factors   (structural header detection)
      -> normalize_factor_returns   (percent -> decimal, sentinel rejection)
      -> FACTOR_RETURN_SCHEMA (Pandera)   (structural checks + unit-confusion tripwire)
      -> factor_return   (idempotent upsert, one source: "kenneth_french")
      -> services.analytics._load_daily_risk_free
            |__ sharpe_ratio(returns, rf)
            |__ capm_beta(asset_returns, spy_returns, rf)
```

* **Deterministic.** No clock is read; `assumptions.as_of` is the last daily
  **return** date. `analytics_start` / `analytics_end` are return-observation
  dates (not price-bar dates).
* **Partial availability is normal.** Every metric object carries a `status`
  (`ok` / `insufficient_observations` / `undefined` / `unavailable`); a security
  with `< 2` bars returns all-suppressed with HTTP 200. One metric is never
  allowed to fail the response.
* **Risk-free rate (implemented, Phase 2B.1).** ADR 0017 defines Sharpe and CAPM
  beta against the Ken French daily `RF` series (ADR 0013), persisted in
  `factor_return` (`factor_name='rf'`, `source='kenneth_french'`) by
  `just ingest-factors` / migration `0003_factor_return`. `_load_daily_risk_free`
  reads it; `None` only when nothing is persisted for the window, in which case
  Sharpe **and** CAPM beta report `status: "unavailable"`,
  `reason: "risk_free_series_not_ingested"` - no constant or zero RF is ever
  substituted (ADR 0013). CAPM beta additionally reports `unavailable` with
  `benchmark_security_not_found` / `benchmark_price_history_unavailable` when
  SPY itself (same price source as the asset) is missing or too short - a
  missing benchmark never fails the other metrics. The engine
  (`sharpe_ratio` / `capm_beta`) owns all date alignment; the service passes
  raw asset / SPY / RF series and never pre-joins them.
* **Same factor infrastructure will carry Phase 3B.** `factor_return` also
  holds `mkt_rf`, `smb`, `hml` (not yet read by any service) and
  `get_factor_panel` returns all four together - the FF3 regression endpoint
  reuses this table and reader pattern without a schema change.
* **No pandas in the router.** SQL stays in the repository; the router owns only
  HTTP status codes.

### Package map (target state at end of Phase 3)

```
src/quantscope/
├── main.py                 app factory; /health, mounts /api/v1 routers
├── config.py               pydantic-settings; env-driven, dev defaults
├── api/
│   ├── routers/            securities (1E); analytics, compare, fundamentals,
│   │                       factors (later)
│   └── schemas.py          response DTOs, distinct from ORM (1E)
├── services/               one module per domain area; fundamentals resolver
├── quant/
│   ├── conventions.py      annualisation factor (252), confidence levels,
│   │                       MIN_OBSERVATIONS thresholds - single source
│   ├── frames.py           Pandera schemas for the DataFrame boundary
│   ├── returns.py          simple/log returns, cumulative, annualised
│   ├── risk.py             volatility, rolling vol, 1-day historical VaR/ES,
│   │                       beta (vs SPY), covariance, correlation
│   ├── drawdown.py         drawdown series, max drawdown, duration/recovery
│   ├── performance.py      Sharpe, Sortino, CAGR, tracking error
│   ├── comparison.py       N-way inner-joined return panel, base-100 normalized
│   │                       performance (NaT anchor, no return divided away),
│   │                       Pearson correlation over the one common panel (3A)
│   ├── factors.py          FF3 OLS regression + HAC (Newey-West) SEs
│   └── calendar.py         XNYS trading calendar wrapper, session alignment
├── logging_setup.py       structured JSON-line logging for CLI jobs
├── data/
│   ├── providers/
│   │   ├── base.py         SecurityReferenceProvider, DailyPriceProvider (+ Fundamentals/Factor later)
│   │   ├── sec_edgar.py    company_tickers_exchange parse + provider
│   │   ├── tiingo.py       Tiingo EOD JSON parse + provider - V1 live (ADR 0022)
│   │   ├── stooq.py        daily price CSV parse + provider - retained, blocked (ADR 0022)
│   │   └── fama_french.py
│   ├── reference.py        SEC-label -> exchange-code map (listed-only in V1),
│   │                       CIK/ticker normalisation, curated-only asset-type
│   ├── security_seed.py    fetch -> normalise -> upsert -> record run
│   ├── prices.py           RawPriceBar -> canonical price frame + drop reasons
│   ├── validation.py       Pandera PRICE_BAR_SCHEMA + validate_price_bars()
│   ├── spot_checks.py      NVDA split + dividend-back-adjustment checks
│   ├── canonical_metrics.py  ordered US-GAAP tag lists per displayed metric
│   └── ingest.py           fetch -> normalise -> validate -> persist + run record (1D)
├── db/
│   ├── base.py             DeclarativeBase (+ constraint naming convention)
│   ├── session.py          engine + sessionmaker + get_session dependency
│   ├── models/             security, price_bar, factor_return,
│   │                       fundamental_fact, data_ingestion_run
│   └── repositories/       securities (upsert + search/get_by_ticker),
│                           prices (upsert + get_price_bars)
└── jobs/
    └── cli.py              seed-securities (1B); ingest-prices (1D) ...
```

Packages for portfolio, backtesting, filings, AI and auth are **not created**
until their phase (see §9).

---

## 5. Quantitative conventions (V1)

Locked in [ADR 0017](./decisions/0017-quant-conventions-and-thresholds.md).
All constants live in `quantscope.quant.conventions`; every affected response
echoes the relevant values in its `assumptions` block.

### Returns
Total return computed from adjusted close (ADR 0012). V1 treats the vendor
adjusted close as the total-return price. The daily return is simple
close-to-close, `r_t = P_t / P_{t-1} - 1`; the first price yields no return
observation. Simple (arithmetic) returns are used everywhere in the V1
user-facing path - there are no log returns in it.

### Volatility
Sample standard deviation (`ddof=1`) of daily total returns, annualised by
**sqrt(252)**. 252 is a trading-session count, not calendar days. A constant
return series has volatility exactly `0.0` - a value, not a suppression.

### Sharpe ratio
`mean(daily excess return) / stdev(daily excess return) * sqrt(252)`, where
daily excess return = daily total return - daily Ken French `RF`. This is
documented as an **annualisation convention**: sqrt(252) assumes i.i.d. daily
returns, so autocorrelation in daily returns biases the annualised figure
(positive autocorrelation inflates it, negative deflates it). Reported, not
corrected, in V1; the `assumptions` block flags it. The risk-free input is a
**daily** series; a scalar *annual* rate, if supplied as a convenience, is
converted to an equivalent daily rate by compounding,
`rf_daily = (1 + rf_annual)^(1/252) - 1`, and subtracted from each daily return
- the annual rate itself is never subtracted. A zero-variance daily excess
series makes the ratio **undefined**, reported as such rather than as a number.

### Beta (user-facing / CAPM)
OLS slope of the security's daily excess return on **SPY's** daily excess
return, both from **total-return-adjusted** prices, over the requested window,
with `RF` = Ken French `RF`. Fitted by `numpy.linalg.lstsq` with an intercept,
on the **inner join** of the asset and benchmark trading dates (and of the
daily risk-free series when supplied). The intercept (`alpha_daily`) is a daily
figure and is not annualised. A zero-variance benchmark excess series makes the
beta **undefined**. If instead only the *asset's* excess return is constant,
beta and alpha are still valid and returned, but `r_squared` is `null`:
`R^2 = 1 - SS_res / SS_tot` is `0 / 0` there, undefined rather than zero.

### Fama-French 3-factor regression
OLS of the security's daily excess return on Ken French **Mkt-RF, SMB, HML**,
with **Newey-West (HAC)** standard errors.

> **SPY beta and the FF Mkt-RF coefficient are different quantities** and are
> reported and labelled separately. SPY is a single S&P 500 ETF; FF Mkt-RF is
> the excess return of the broad cap-weighted US market portfolio (all listed
> common stock, dividends and delistings included). Their market-sensitivity
> estimates legitimately differ; neither is "the" beta.

### Historical VaR / Expected Shortfall
* **1-trading-day horizon only** in V1, historical (empirical) method.
* `VaR_alpha = -(empirical (1 - alpha) quantile of daily total returns)`,
  reported as a **positive loss**.
* `ES_alpha = -(mean of daily returns at or below that quantile)`.
* The quantile is the **lower empirical order statistic** (no interpolation):
  with returns sorted ascending, `r* = value at index floor((1 - alpha)(n - 1))`.
  It is an actually observed return and is deterministic when several
  observations tie at the tail. The ES tail is `{ r_t : r_t <= r* }` (inclusive).
* Both figures are positive loss magnitudes; a sample with no losses in the tail
  can therefore yield a negative VaR (a gain), reported as-is, not floored at
  zero.
* **No square-root-of-time or any multi-day scaling.** Multi-day horizons are
  out of scope until a later phase adds a defensible method.
* Confidence levels reported: **95% and 99%**.

### Minimum observation thresholds
Centralised. A metric computed from fewer usable daily observations than its
threshold is **suppressed**; the response carries a structured reason
`{metric, status: "insufficient_observations", required, observations_used}`.
Structurally invalid inputs (non-datetime index, unsorted or duplicated dates,
non-finite values, non-positive prices) are rejected with an explicit error -
suppression is only for a well-formed series that is merely too short. A metric
whose denominator has zero variance is reported `{..., status: "undefined"}`.

| Threshold (usable daily obs) | Metrics gated                                        |
|------------------------------|-----------------------------------------------------|
| **60**                       | returns, annualised volatility, drawdown / max drawdown |
| **126**                      | Sharpe, beta, historical VaR, historical ES          |
| **250**                      | FF3 regression                                       |

### Multi-security comparison
* One **common trading-date panel**, built by **inner join** on trading date
  across every requested security (plus SPY / FF factors where a metric needs
  them). The correlation matrix and every cross-security beta are computed from
  that single aligned panel.
* **No pairwise-complete / pairwise-deletion correlation in V1.**
* The response exposes `observations_used`, `aligned_start`, `aligned_end`.
  Consequence, surfaced to the user: including a short-history security shrinks
  the common window for the entire comparison.

---

## 6. Frontend

* **Next.js (App Router) + TypeScript.** Server components for shell/layout;
  client components for interactive, data-driven views.
* **TanStack Query** is the single data layer for server state (ADR 0010):
  caching, retry, background refetch, request de-duplication. No Redux/Zustand
  for server data.
* **API client** lives in `src/lib/api/` (typed fetchers + TanStack Query
  hooks); components never call `fetch` directly. Types are hand-written against
  the 1E schema for now; an OpenAPI-generated client can replace them later.
* **Charting:** hand-drawn SVG for the daily price line (small, restrained,
  matches the approved design - no charting dependency in Phase 1F). A richer
  library may be revisited for later OHLC / correlation-heatmap needs.
* Routes at end of Phase 3: `/securities/[ticker]`, `/compare`.

---

## 7. Minimum database schema (MVP)

Five tables. One extension (`pg_trgm`, for ticker/name search). Full column
lists and the rationale for what is intentionally *absent* are in
[ADR 0004](./decisions/0004-postgresql-and-provenance-fields.md),
[ADR 0011](./decisions/0011-security-id-as-universal-foreign-key.md),
[ADR 0012](./decisions/0012-total-return-via-vendor-adjusted-close.md),
[ADR 0013](./decisions/0013-risk-free-rate-from-fama-french-series.md) and
[ADR 0021](./decisions/0021-security-universe-seeding.md).

| Table                 | Purpose                                             | Key provenance columns                     |
|-----------------------|-----------------------------------------------------|--------------------------------------------|
| `security`            | Reference data for the searchable US-equity universe, seeded from SEC (ADR 0021). Internal `id` PK; **all FKs reference `security_id`, never `ticker`**. `exchange` is a MIC-style code **normalised from the SEC exchange label** (single-source, not verified listing metadata); V1 is exchange-listed only (OTC excluded). `asset_type` / `cik` are **nullable** - set only when reliably determinable, never guessed. | -                                          |
| `price_bar`           | Daily OHLCV per security. Both raw `close` and vendor `adj_close` stored. | `source`, `ingested_at`; PK `(security_id, trade_date, source)` |
| `factor_return`       | Daily Fama-French factor returns (`mkt_rf`, `smb`, `hml`, `rf`), decimal daily returns (source percent / 100). `frequency` column keeps monthly factors possible later. No FK to `security` - factors are market-wide. | `source` (`kenneth_french`), `ingested_at`; PK `(factor_name, frequency, trade_date, source)` |
| `fundamental_fact`    | Point-in-time company facts from SEC EDGAR. Restatements inserted as new rows; resolved metrics record which tag/accession they used. | `filed_date` (mandatory), `accession_no`, `form`, `taxonomy`, `tag`, `unit`, `source`, `ingested_at` |
| `data_ingestion_run`  | Audit row per ingestion invocation (status, rows, error, time range). | is the provenance record                   |

Migration order: **0001** `security`, `price_bar`, `data_ingestion_run`,
`pg_trgm` (Phase 1A) -> **0002** `security.asset_type` nullable (Phase 1B,
ADR 0021) -> **0003 (M2)** `factor_return` (Phase 2B.1, *complete*) -> **M3**
`fundamental_fact` (Phase 3).

---

## 8. API surface (end of Phase 3)

All under `/api/v1`. Every analytics response embeds an `assumptions` object and
may report individual metrics as suppressed with a structured reason (§5).

> Phase 1E ships the first three rows as **read-only** routes served at the root
> (like `/health`), not yet under `/api/v1`: `GET /securities?q=`,
> `GET /securities/{ticker}`, `GET /securities/{ticker}/prices?start&end&source`.
> `/prices` returns a single provider's series (defaulting to `price_provider`)
> and never merges sources. Prices are exact `NUMERIC(18,6)` / `Decimal` in the
> DB and domain layer, converted to `float` only at the JSON boundary, so the
> API emits numbers (`"close": 100.1`) - the precision the quant engine uses.
>
> Phase 2B ships `GET /securities/{ticker}/analytics?start&end&source`, also at
> the root. It resolves the ticker (404 on miss), loads one source's persisted
> **adjusted-close** bars for the window, derives daily simple returns once, and
> runs the pure Phase 2A engine. Each metric object carries a `status`
> (`ok` / `insufficient_observations` / `undefined` / `unavailable`); one
> unavailable metric never fails the response. **Phase 2B.1 wires Sharpe and
> CAPM beta to the persisted Kenneth French daily `RF`** (migration `0003`,
> `just ingest-factors`); they report `unavailable` only when RF (or, for beta,
> SPY) is genuinely not persisted - see §5. Metric numbers are `float` end to
> end, so they serialise as JSON numbers. No `benchmark` / `window` query
> params: beta is always vs SPY, and the window is plain `start`/`end` dates.

| Method & path                                   | Purpose                                                        |
|-------------------------------------------------|---------------------------------------------------------------|
| `GET /securities?query=`                        | Search the seeded universe (trigram on ticker + name).        |
| `GET /securities/{ticker}`                      | Security profile.                                             |
| `GET /securities/{ticker}/prices?start&end`     | Historical daily bars.                                        |
| `GET /securities/{ticker}/analytics?start&end&source` | Return summary / volatility / Sharpe / max drawdown / CAPM beta (vs SPY) / 1-day historical VaR & ES at 95% and 99% + `assumptions`. One source, adjusted close, per-metric `status`. Sharpe & beta read the persisted Kenneth French `RF` (Phase 2B.1); `unavailable` only when RF (or SPY, for beta) is not persisted. Shipped in Phase 2B / 2B.1. |
| `GET /securities/{ticker}/risk?confidence&level` | 1-day historical VaR / ES detail (95% and 99%).              |
| `GET /securities/{ticker}/fundamentals`         | Revenue, earnings, growth, market cap, P/E, forward P/E, P/S. Each value resolved via the canonical-metric mapping and tagged with `tag`, `period_end`, `filed_date`, `accession_no`; **returned as `unavailable` (with a reason) when no mapped tag is present** - never guessed. |
| `GET /securities/{ticker}/factors?model=ff3&start&end` | FF3 regression: Mkt-RF / SMB / HML coefficients, HAC standard errors, t-stats, R², n. Response states explicitly that the Mkt-RF coefficient is **not** the SPY CAPM beta. |
| `GET /compare?tickers=A,B,...&start&end&source` | 2-8 distinct tickers -> one N-way inner-joined return panel -> base-100 normalized performance (every aligned return compounded, none divided away) + Pearson correlation matrix + `observations_used`, `aligned_start`, `aligned_end`. Flat provenance fields (no nested `assumptions`). `status`: `ok` / `insufficient_observations` (panel < `MIN_OBS_COMPARISON` = 60) / `unavailable` (any ticker has < 2 persisted bars, lists every offender). Shipped in Phase 3A. |

`/health` (liveness) is served at the root, outside `/api/v1`.

---

## 9. Deliberately deferred

Kept reachable by the architecture; **not built or scaffolded** in the MVP.

| Deferred                                              | Why it is safe to defer                                                             |
|------------------------------------------------------|------------------------------------------------------------------------------------|
| Redis, task queue, workers, async job infra          | Ingestion is synchronous CLI; analytics compute is sub-second. Add with backtesting. |
| Authentication, users, `owner_id` columns            | Nothing in the MVP is user-scoped. Adding `owner_id` later is a routine migration. |
| `ticker_history` table                               | Single current ticker on `security`; FKs already use `security_id` (ADR 0011).     |
| `corporate_action` table / self-computed adjustment  | Use vendor `adj_close`; raw `close` retained for later reconstruction (ADR 0012).  |
| `risk_free_rate` table                               | Use the Ken French `RF` series in `factor_return` (ADR 0013).                      |
| Derived `valuation_snapshot` table                   | Ratios computed on the fly from `fundamental_fact` + latest price.                 |
| `benchmark_price` table                              | The benchmark is an ordinary `security` row (`SPY`).                               |
| `provider_request_log`                               | `data_ingestion_run` covers the audit trail that matters now.                      |
| Multi-day VaR / ES, square-root-of-time scaling      | V1 is 1-trading-day historical only (ADR 0017). Needs a defensible method first.   |
| Pairwise-complete correlation                        | V1 uses one inner-joined panel (ADR 0017).                                         |
| `portfolio*`, `backtest*`, `filing*`, `ai_*` tables  | No portfolio, backtesting, filings or AI features in the MVP.                      |
| `quantscope.backtest`, `quantscope.ai` packages      | Not created. The pure `quant` functions are what a future engine will consume.     |
| Ledoit-Wolf / shrinkage covariance                   | Sample covariance is adequate for small comparison sets; documented as a limitation. |
| Rolling factor betas, FF5, momentum factor           | Full-sample FF3 with HAC SEs. `factor_return` schema already allows more factors.  |
| Multi-exchange calendars, non-USD, ADRs              | XNYS + USD asserted at ingestion; violations rejected, never silently coerced.     |
| OTC securities in the seeded universe                | V1 is exchange-listed only; OTC recognised but rejected `unsupported_exchange_v1:OTC` (ADR 0021). Re-enable via `SUPPORTED_EXCHANGES`, no model change. |
| Cross-provider listing-venue verification            | `security.exchange` is a single-source normalisation of the SEC label (ADR 0021). |
| Monte Carlo simulation                               | Portfolio-phase feature.                                                          |

Known data limitations accepted for the MVP (surfaced in responses, not hidden):
survivorship bias in free price data, revision blindness outside fundamentals,
regime dependence of historical VaR/ES, small-sample instability in factor
regressions, and sqrt(252)/sqrt-time annualisation under return autocorrelation.

---

## 10. Roadmap (MVP = Phases 0-3)

### Phase 0 - Skeleton & guardrails  *(complete, in review)*
Monorepo layout; `docker-compose` (db + backend + frontend); `uv` / `pnpm`
tooling; `justfile`; Ruff, mypy (strict on `quant`), pytest, `import-linter`
contract; GitHub Actions CI; pre-commit; Alembic wired with **no migration
yet**; FastAPI app factory + `/health`; Next.js shell with the TanStack Query
provider; `.env.example`; README; `docs/architecture.md` + ADRs 0001-0022.

### Phase 1 - Search + market-data ingestion
Delivered in sub-phases 1A-1F. Each is reviewed and approved before the next
begins; no sub-phase pulls work forward from a later one.

- **1A** *(complete)* - ORM models + migration `0001` (`security`, `price_bar`,
  `data_ingestion_run`, `pg_trgm`); model/constraint tests against PostgreSQL.
- **1B** *(complete)* - SEC security-universe seeding from
  `company_tickers_exchange.json`: source adapter, exchange-label normalisation
  (exchange-listed only; OTC excluded), CIK/ticker normalisation, curated-only
  asset-type classification, idempotent upsert, `quantscope seed-securities` CLI
  + `just seed`, structured logging, `data_ingestion_run` recording. Migration
  `0002` (`asset_type` nullable).
- **1C** *(complete)* - `DailyPriceProvider` Protocol + `RawPriceBar`;
  `normalize_price_bars` -> canonical typed price-bar frame; `PRICE_BAR_SCHEMA`
  (Pandera) + `validate_price_bars` with **structured validation / drop
  reasons**; hand-authored **NVDA 10:1 split adjusted-price spot-check**; Stooq
  adapter (synthetic fixtures; live fetch anti-bot blocked). **No persistence,
  APIs, or frontend.**
- **1C.1** *(complete)* - **Tiingo adapter** adopted as the V1 live provider
  (ADR 0022): `TiingoDailyPriceProvider` + pure `parse_tiingo_eod`, config +
  `QUANTSCOPE_TIINGO_TOKEN`, error mapping, synthetic-fixture tests, guarded
  live smoke tests, live-verified NVDA split + dividend-back-adjustment
  spot-checks (2026-09-02). Stooq adapter retained.
- **1D** *(complete)* - validated price-bar **persistence** into `price_bar`
  (`db/repositories/prices.py`, idempotent upsert on
  `(security_id, trade_date, source)`); `data/ingest.py` orchestration
  (fetch -> normalise -> validate -> persist) with `data_ingestion_run`
  start/success/partial/failed accounting, one run + one transaction per ticker;
  `quantscope ingest-prices` CLI (+ `just ingest-prices`); `just ingest-demo`
  for the six demo tickers. Provider-independent normalisation, the Pandera
  schema and `RawPriceBar` are unchanged. No migration.
- **1E** *(complete)* - read-only REST: `GET /securities` (trigram search on
  ticker/name, exact-ticker-first ordering, bounded `limit`/`offset`),
  `GET /securities/{ticker}` (normalised lookup, 404 on miss),
  `GET /securities/{ticker}/prices` (`start`/`end`/`source`, ascending
  `trade_date`, single source - defaults to `price_provider`, never merged;
  prices exact `Decimal` internally, serialised as JSON numbers at the API
  boundary). `api/routers/securities.py` + `api/schemas.py` + read functions in
  the existing repositories; no service layer. No migration.
- **1F** *(in review)* - frontend market-data experience against the 1E API
  only: landing **search** (debounced `GET /securities?q=`, keyboard nav),
  **ticker page** `/securities/[ticker]` (server component -> typed fetch ->
  `notFound()` on 404 -> client chart panel), **price chart** plotting
  `adj_close` (ADR 0012) as a hand-drawn SVG line + area with `1Y/3Y/5Y/MAX`
  range controls (-> API `start`), optional dashed raw-`close` overlay,
  crosshair tooltip, and a shown resolved `source`. `next/font` (Inter + IBM
  Plex Mono); no charting dependency; Vitest + Testing Library. Light theme
  only. **No analytics, no backend change, no migration.**

No committed datasets - vendor data is never committed to the repository; tests
use synthetic / hand-authored fixtures and documented local-fetch instructions
(ADR 0015).

### Phase 2 - Deterministic single-name analytics
Delivered in sub-phases.

- **2A** *(complete)* - `quant/conventions`, `quant/{returns,risk,drawdown,
  performance,frames}` with golden-value + edge-case tests; centralised
  observation thresholds (60/126/250) with structured `InsufficientObservations`
  / `UndefinedResult`; CI-enforced pure boundary.
- **2B** *(complete)* - `quantscope.services.analytics` +
  `GET /securities/{ticker}/analytics`: return summary, annualised volatility,
  max-drawdown summary, 1-day historical VaR/ES at 95% and 99%, plus the ADR
  0005 `assumptions` block, all from persisted adjusted-close bars for one
  source. Sharpe and CAPM beta wired but reported `unavailable` (no RF ingested
  yet). No migration. No frontend.
- **2B.1** *(complete)* - **migration `0003_factor_return`** (ADR 0009: `mkt_rf`
  / `smb` / `hml` / `rf`, decimal daily returns, PK
  `(factor_name, frequency, trade_date, source)`, no FK to `security`);
  `quantscope.data.providers.french_factors` (structural CSV parsing) +
  `quantscope.data.factors` (percent -> decimal, sentinel rejection, the
  `abs(value) < 0.5` unit-confusion tripwire) + `quantscope.data.factor_ingest`
  + `db.repositories.factors`, idempotent, `quantscope ingest-factors` /
  `just ingest-factors`. `services.analytics._load_daily_risk_free` now reads
  real `RF`; **Sharpe and CAPM beta become `ok`** whenever RF (and, for beta,
  SPY) is persisted with enough overlap - `insufficient_observations` /
  `undefined` / `unavailable` otherwise, per ADR 0017 / ADR 0013. No frontend;
  no FF3 regression yet.
- **M2 + Phase 3B** - FF3 regression (Mkt-RF/SMB/HML OLS + Newey-West HAC),
  reusing `factor_return` and `get_factor_panel` as-is; rolling series +
  drawdown time-series endpoints. Frontend: metrics panel, rolling and drawdown
  charts.

### Phase 3 - Comparison, correlation, fundamentals, factor regression
SEC EDGAR fundamentals ingestion (`filed_date`, `accession_no`);
**canonical-metric mapping layer** (ordered US-GAAP tag sets per displayed
metric; `unavailable` rather than guessed); on-the-fly valuation ratios;
`POST /compare` on one inner-joined panel with correlation matrix and alignment
metadata; `quant/factors` FF3 OLS + HAC SEs; `GET /securities/{ticker}/factors`
with the SPY-beta-vs-Mkt-RF distinction stated. Frontend: compare view +
correlation heatmap, fundamentals tables, factor-exposure view, dashboard polish
pass. **Migration M3.**

### Beyond the MVP (architecture-compatible, not scheduled here)
Phase 4 portfolio analytics · Phase 5 backtesting engine · Phase 6 SEC filings
browser · Phase 7 AI research assistant (deterministic tool-calling) · Phase 8
AI evaluation harness.

---

## 11. Technology decisions at a glance

| Area              | Choice                                              | ADR |
|-------------------|----------------------------------------------------|-----|
| Architecture      | Modular monolith                                    | 0001 |
| Analytics core    | Pure `quant` package, CI-enforced dependency contract | 0002 |
| Data access       | Provider `Protocol` + separate ingestion            | 0003 |
| Database          | PostgreSQL + provenance columns                     | 0004 |
| API contract      | `assumptions` block in every analytics response     | 0005 |
| Market scope      | US equities, XNYS calendar only                     | 0006 |
| Infrastructure    | No Redis / queue / workers / auth in V1             | 0007 |
| Price provider    | **Tiingo adopted** as V1 live provider; Stooq adapter retained (anti-bot blocked) | 0008, 0022 |
| Factor data       | Daily Fama-French; schema allows monthly            | 0009 |
| Frontend data     | TanStack Query                                      | 0010 |
| Identity          | `security_id` is the universal FK                   | 0011 |
| Returns basis     | Total return via vendor adjusted close              | 0012 |
| Risk-free rate    | Ken French `RF` series                              | 0013 |
| Python tooling    | uv + Ruff + mypy + pytest + import-linter           | 0014 |
| Provenance        | No redistributed vendor datasets in the repo        | 0015 |
| Fundamentals      | Canonical-metric mapping; unavailable, not guessed  | 0016 |
| Quant conventions | Annualisation, beta/FF, 1-day VaR/ES, obs thresholds | 0017 |
| DataFrame contracts | pandas + Pandera at the boundary; no wrappers     | 0018 |
| Product priorities | Correctness > architecture > dashboard > setup > methodology > breadth | 0019 |
| Task runner       | Thin cross-platform `justfile`; README keeps raw commands | 0020 |
| Security seeding  | SEC reference data; label-derived exchange codes; exchange-listed only (OTC excluded); nullable asset_type; idempotent upsert | 0021 |
| Price data layer  | Provider Protocol + `RawPriceBar`; pandas normalisation; Pandera `PRICE_BAR_SCHEMA`; NVDA split spot-check | 0022 |
