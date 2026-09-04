/**
 * Typed call to the Phase 3A `GET /compare` endpoint. No React here - wrapped
 * by `useComparison` in `./hooks` for client components.
 */

import { apiFetch } from "./client";
import type { ComparisonResponse } from "./types";

/** Mirrors `MIN_TICKERS`/`MAX_TICKERS` in `backend/.../api/routers/compare.py`. */
export const MIN_COMPARISON_TICKERS = 2;
export const MAX_COMPARISON_TICKERS = 8;

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
}

export interface ComparisonQuery {
  start?: string;
  end?: string;
  source?: string;
  init?: RequestInit;
}

/**
 * Multi-security comparison over one common aligned-return panel (2-8
 * distinct tickers). Same `start`/`end` semantics as `getSecurityAnalytics`.
 * The frontend never computes alignment, normalization, or correlation
 * itself - it only requests and renders what the API returns.
 */
export function getComparison(
  tickers: readonly string[],
  { start, end, source, init }: ComparisonQuery = {},
): Promise<ComparisonResponse> {
  return apiFetch<ComparisonResponse>(
    `/compare${query({ tickers: tickers.join(","), start, end, source })}`,
    init,
  );
}
