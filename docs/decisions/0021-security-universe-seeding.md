# 21. Security-universe seeding from SEC reference data

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

Phase 1B populates `security` with a searchable universe of US securities from
SEC's public `company_tickers_exchange.json` (`{fields, data}` rows of
`cik, name, ticker, exchange`). The file is not committed (ADR 0015). It carries
no asset-type field, its `exchange` values are inconsistent free text, and it
lists only current registrants.

## Decision

### Structure
`quantscope.data.providers` (source adapters), `quantscope.data.reference`
(pure normalisation + classification), `quantscope.data.security_seed`
(orchestration + `data_ingestion_run` recording),
`quantscope.db.repositories.securities` (idempotent upsert),
`quantscope.jobs.cli` (`quantscope seed-securities`). The request path never
imports any of it.

### Exchange normalisation

`security.exchange` is a **normalised code derived from the single exchange
label SEC publishes** in `company_tickers_exchange.json`. It is **not
independently verified authoritative listing-venue metadata**: the SEC label is
mapped mechanically to a MIC-style code, from one source, with no cross-provider
check. It can differ from a security's true primary-listing MIC - for example
the live SEC file labels `SPY` as `"NYSE"` (→ `XNYS`), though SPY primarily
trades on NYSE Arca (`ARCX`). Treat `security.exchange` as "the SEC label,
normalised", not as a verified fact about where the security lists.

The mapping (case-insensitive, trimmed): `NYSE→XNYS`, `Nasdaq→XNAS`,
`NYSE American / NYSE MKT / AMEX→XASE`, `NYSE Arca→ARCX`, `Cboe / BATS / BZX→BATS`,
`IEX→IEXG`, and `OTC→OTC` (a recognised sentinel; over-the-counter has no listing
MIC). An **unmapped or missing** label rejects the record
(`unmapped_or_missing_exchange:<raw>`) - never a guess.

**V1 seeds exchange-listed US securities only.** `OTC` is *recognised* but
**excluded** from the V1 universe: matching records are rejected with reason
`unsupported_exchange_v1:OTC`, not silently dropped. OTC brings extra
price-availability, liquidity, market-calendar, ticker-normalisation and
data-quality concerns that are outside the MVP. The normaliser separates
*recognised* codes (`RECOGNISED_EXCHANGES`) from *accepted* codes
(`SUPPORTED_EXCHANGES = RECOGNISED_EXCHANGES − {"OTC"}`); including OTC later is
adding `"OTC"` to `SUPPORTED_EXCHANGES` plus the downstream handling it needs -
**no model change**.

*Trade-off:* sub-market tiers (Nasdaq Global Select vs Capital Market, etc.) are
collapsed. SEC does not carry them, every supported venue shares the XNYS/US
session calendar (ADR 0006) so no analytics branch on tier, and the codes align
with `exchange_calendars`. A DB `CHECK` on `security.exchange` is deferred
(enforced in the normaliser for now) to leave the Phase 1A schema otherwise
untouched.

This phase does **not** add a second venue source or attempt cross-provider
venue verification.

### Asset-type classification
`company_tickers_exchange.json` has no asset-type field, so `asset_type` is set
**only** from a small hand-maintained, source-cited list of unmistakable ETFs
(`SPY, QQQ, IWM, DIA, VOO, VTI, IVV`). Every other record gets
`asset_type = NULL`. No inference from names ("ETF"/"Trust"/"Fund"), exchange,
or filing type. This requires **migration `0002`**: `security.asset_type`
becomes nullable and its CHECK becomes
`asset_type IS NULL OR asset_type IN ('common_stock','etf','index')`.

### CIK
Zero-padded to exactly 10 digits. A present-but-non-numeric or >10-digit value
rejects the record (`invalid_cik:...`). Absent/empty → `NULL`.

### Idempotent upsert
De-duplicate the snapshot by ticker (first wins;
`duplicate_ticker_in_snapshot`), then `INSERT ... ON CONFLICT (ticker) DO UPDATE
SET name/cik/exchange/asset_type/updated_at=now() WHERE any of those IS DISTINCT
FROM the incoming value`. New ticker → INSERT (fresh identity `id`); existing →
UPDATE in place (`id` and `created_at` preserved); unchanged → no-op. Re-running
on identical input changes 0 rows and preserves every `id`.

### Lifecycle
Rows absent from a later snapshot are **left untouched** - no delete, no
`is_active`/`delisted_date` change. SEC absence is not a reliable delisting
signal (ticker change, filing gap, data quirk). A future phase with a real
delisting feed can flip lifecycle state.

### Run recording & logging
Each real run writes a `data_ingestion_run` row (`source`, `entity='securities'`,
`status`, `rows_written = inserted + updated`, `started_at`/`finished_at`);
`status` is `partial` when any record was rejected/de-duplicated, `success`
otherwise, `failed` (recorded in its own transaction) on an exception.
Structured JSON-line logs carry per-stage counts and every rejection reason.

## Consequences

- Honest data: `asset_type` and `cik` are `NULL` rather than fabricated;
  unclassifiable rows are excluded with a logged reason.
- V1 universe is exchange-listed only; OTC records are accounted for
  (`unsupported_exchange_v1:OTC`), not lost.
- `security.exchange` reflects the SEC label, normalised - not a verified listing
  venue. Downstream code must not treat it as authoritative.
- Re-seeding is safe and cheap; IDs are stable for downstream FKs (ADR 0011).
- Migration `0002` is the one schema change in Phase 1B.
- `exchange` holds only supported MIC-style codes; an optional `CHECK` can lock
  the vocabulary later.

## Alternatives considered

- **Keep SEC's raw exchange text** - rejected: unstable, inconsistent, mixes
  granularity.
- **Seed OTC with `exchange='OTC'`** - rejected for V1: pulls in the
  price/liquidity/calendar/data-quality problems the MVP is not ready for. The
  code keeps OTC recognised so it can be re-enabled deliberately.
- **Cross-check the venue against a second provider** - out of scope for this
  phase; `security.exchange` stays a single-source normalisation.
- **Default `asset_type='common_stock'` for everything not in the ETF map** -
  rejected: a heuristic with ETF/ADR/unit/warrant false positives; violates
  "don't guess".
- **Restrict the universe to rows we can fully classify** - rejected: would drop
  most of the universe and defeat "searchable".
