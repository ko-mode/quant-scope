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
