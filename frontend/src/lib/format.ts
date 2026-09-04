/**
 * Pure presentation / query helpers. No React, no I/O - unit-tested directly.
 */

import type { PriceBar, SecurityRead } from "./api/types";

export const RANGE_OPTIONS = ["1Y", "3Y", "5Y", "MAX"] as const;
export type RangeOption = (typeof RANGE_OPTIONS)[number];

const RANGE_YEARS: Record<Exclude<RangeOption, "MAX">, number> = { "1Y": 1, "3Y": 3, "5Y": 5 };

/**
 * Translate a range button into Phase 1E `start` / `end` query params.
 *
 * `1Y/3Y/5Y` -> `{ start: <today - N years, ISO date> }`; `end` is omitted so
 * the API returns through the latest persisted bar. `MAX` -> `{}` (no `start`).
 */
export function rangeToParams(range: RangeOption, today: Date = new Date()): { start?: string } {
  if (range === "MAX") return {};
  const start = new Date(
    Date.UTC(today.getUTCFullYear() - RANGE_YEARS[range], today.getUTCMonth(), today.getUTCDate()),
  );
  return { start: start.toISOString().slice(0, 10) };
}

export interface PricePoint {
  time: string; // ISO date
  value: number; // adj_close
}

/**
 * The chart series. The plotted value is **`adj_close`** - the V1 total-return
 * convention (ADR 0012), not raw `close`. Ascending order is preserved.
 */
export function toPriceSeries(bars: readonly PriceBar[]): PricePoint[] {
  return bars.map((bar) => ({ time: bar.trade_date, value: bar.adj_close }));
}

export function securityHref(ticker: string): string {
  return `/securities/${encodeURIComponent(ticker.trim().toUpperCase())}`;
}

const ASSET_TYPE_LABEL: Record<string, string> = {
  common_stock: "Common stock",
  etf: "ETF",
  index: "Index",
};

export function assetTypeLabel(assetType: string | null): string {
  if (!assetType) return "—";
  return ASSET_TYPE_LABEL[assetType] ?? assetType;
}

export function statusLabel(security: Pick<SecurityRead, "is_active" | "delisted_date">): string {
  if (security.is_active) return "Active";
  return security.delisted_date ? `Inactive · delisted ${security.delisted_date}` : "Inactive";
}

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatPrice(value: number | null | undefined): string {
  return value == null || Number.isNaN(value) ? "—" : USD.format(value);
}

const INT_FMT = new Intl.NumberFormat("en-US");

export function formatVolume(value: number | null | undefined): string {
  return value == null || Number.isNaN(value) ? "—" : INT_FMT.format(value);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parseISO(iso: string): Date {
  return new Date(`${iso}T00:00:00Z`);
}

/** "2024-06-10" -> "Jun 10, 2024" (UTC). */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = parseISO(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
}

/** "2024-06-10" -> "Jun '24" (compact axis label). */
export function formatAxisDate(iso: string): string {
  const d = parseISO(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${MONTHS[d.getUTCMonth()]} '${String(d.getUTCFullYear()).slice(2)}`;
}

export interface EmptyState {
  title: string;
  message: string;
}

/**
 * Which empty-chart copy to show. Phase 1E does not distinguish "never ingested"
 * from "gap in this range" without a second request, so an empty `MAX` means
 * there is nothing at all, while an empty narrower range only tells us there is
 * nothing *in that window* - the copy must not claim history exists elsewhere.
 */
/**
 * Percent formatting for analytics fields (return, volatility, drawdown,
 * VaR / ES). Purely presentational: multiplies the backend's decimal fraction
 * by 100 and fixes the decimals - it does not alter magnitude or sign. The
 * backend reports VaR / ES as **positive loss magnitudes** (ADR 0017); this
 * function never flips or reinterprets a sign, it only formats whatever
 * number it is given.
 */
export function formatPercent(value: number | null | undefined, decimals = 2): string {
  return value == null || Number.isNaN(value) ? "—" : `${(value * 100).toFixed(decimals)}%`;
}

/** Plain fixed-decimal formatting for ratio metrics (Sharpe, beta, r-squared). */
export function formatRatio(value: number | null | undefined, decimals = 2): string {
  return value == null || Number.isNaN(value) ? "—" : value.toFixed(decimals);
}

/** "52 / 126 observations" for an `insufficient_observations` metric. */
export function observationsFraction(
  used: number | null | undefined,
  required: number | null | undefined,
): string {
  if (used == null || required == null) return "";
  return `${used} / ${required} observations`;
}

/**
 * Human label for a metric's `reason` when `status === "unavailable"`. Known
 * codes come from `quantscope.services.analytics`; an unrecognised code (e.g.
 * a future addition) falls back to a de-slugged version rather than hiding it.
 */
const UNAVAILABLE_REASON_LABEL: Record<string, string> = {
  risk_free_series_not_ingested: "RF not ingested",
  benchmark_security_not_found: "SPY benchmark unavailable",
  benchmark_price_history_unavailable: "Benchmark history unavailable",
};

export function unavailableReasonLabel(reason: string | null | undefined): string {
  if (!reason) return "Unavailable";
  return UNAVAILABLE_REASON_LABEL[reason] ?? reason.replaceAll("_", " ");
}

/** "Jun 10, 2021 – Jun 9, 2025 · 1,006 observations" (or just the count when
 * no return series could be formed - `analytics_start`/`end` are then `null`). */
export function analyticsRangeLabel(analytics: {
  analytics_start: string | null;
  analytics_end: string | null;
  return_observations: number;
}): string {
  const { analytics_start, analytics_end, return_observations } = analytics;
  const noun = return_observations === 1 ? "observation" : "observations";
  if (!analytics_start || !analytics_end) return `${return_observations} ${noun}`;
  return `${formatDate(analytics_start)} – ${formatDate(analytics_end)} · ${return_observations} ${noun}`;
}

/**
 * Pearson correlation cell formatting for the Phase 3A comparison matrix.
 * `null` (zero-variance ticker, including its own diagonal) renders as "—",
 * never `"1.00"` or `"0.00"` - see `CorrelationMatrix` in `api/types`.
 */
export function formatCorrelation(value: number | null | undefined): string {
  return value == null || Number.isNaN(value) ? "—" : value.toFixed(2);
}

export function emptyStateFor(range: RangeOption): EmptyState {
  if (range === "MAX") {
    return {
      title: "No price history available",
      message: "No price observations have been ingested for this security yet.",
    };
  }
  return {
    title: "No observations in this range",
    message: "No observations available in this range. Try MAX to check for earlier price history.",
  };
}
