/**
 * Typed calls to the Phase 1E read-only endpoints. No React here - these run in
 * server components (pass `{ cache: "no-store" }`) and are also wrapped by the
 * hooks in `./hooks` for client components.
 */

import { apiFetch } from "./client";
import type {
  AnalyticsResponse,
  FactorsResponse,
  PriceHistoryResponse,
  SecurityListResponse,
  SecurityRead,
} from "./types";

/** Rows requested for the price chart - the API's own maximum, so `MAX` is never truncated. */
export const PRICE_ROW_LIMIT = 20_000;

/**
 * The search UI calls the API once the trimmed query has at least this many
 * characters. 1 = search on any input; the debounce does the rate limiting.
 */
export const MIN_SEARCH_LENGTH = 1;

/** Rows requested per search page. */
export const SEARCH_ROW_LIMIT = 20;

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
}

export interface SearchOptions {
  limit?: number;
  offset?: number;
  init?: RequestInit;
}

export function searchSecurities(
  q: string,
  { limit = SEARCH_ROW_LIMIT, offset, init }: SearchOptions = {},
): Promise<SecurityListResponse> {
  return apiFetch<SecurityListResponse>(`/securities${query({ q, limit, offset })}`, init);
}

export function getSecurity(ticker: string, init?: RequestInit): Promise<SecurityRead> {
  return apiFetch<SecurityRead>(`/securities/${encodeURIComponent(ticker)}`, init);
}

export interface PriceQuery {
  start?: string;
  end?: string;
  source?: string;
  limit?: number;
  init?: RequestInit;
}

export function getSecurityPrices(
  ticker: string,
  { start, end, source, limit = PRICE_ROW_LIMIT, init }: PriceQuery = {},
): Promise<PriceHistoryResponse> {
  return apiFetch<PriceHistoryResponse>(
    `/securities/${encodeURIComponent(ticker)}/prices${query({ start, end, source, limit })}`,
    init,
  );
}

export interface AnalyticsQuery {
  start?: string;
  end?: string;
  source?: string;
  init?: RequestInit;
}

/**
 * Deterministic single-name analytics (Phase 2B / 2B.1). Same `start`/`end`
 * semantics as `getSecurityPrices`: omit both for the full persisted history.
 * The frontend never computes any of this - it only requests and renders it.
 */
export function getSecurityAnalytics(
  ticker: string,
  { start, end, source, init }: AnalyticsQuery = {},
): Promise<AnalyticsResponse> {
  return apiFetch<AnalyticsResponse>(
    `/securities/${encodeURIComponent(ticker)}/analytics${query({ start, end, source })}`,
    init,
  );
}

export interface FactorsQuery {
  start?: string;
  end?: string;
  source?: string;
  init?: RequestInit;
}

/**
 * SPY CAPM regression + Fama-French 3-factor regression, both with
 * Newey-West (HAC) inference (Phase 3B). Same `start`/`end` semantics as
 * `getSecurityAnalytics`. All regression math happens on the backend - this
 * only requests and returns the response.
 */
export function getSecurityFactors(
  ticker: string,
  { start, end, source, init }: FactorsQuery = {},
): Promise<FactorsResponse> {
  return apiFetch<FactorsResponse>(
    `/securities/${encodeURIComponent(ticker)}/factors${query({ start, end, source })}`,
    init,
  );
}
