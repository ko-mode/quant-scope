"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { rangeToParams, type RangeOption } from "@/lib/format";
import { getSecurityAnalytics, getSecurityPrices, MIN_SEARCH_LENGTH, searchSecurities } from "./securities";
import type { AnalyticsResponse, PriceHistoryResponse, SecurityListResponse } from "./types";

/**
 * Interactive search. `q` should already be debounced by the caller. The query
 * key includes `q`, so React Query only ever surfaces the current term's result -
 * a slow response for an old term cannot overwrite a newer one.
 */
export function useSecuritySearch(q: string) {
  const term = q.trim();
  return useQuery<SecurityListResponse>({
    queryKey: ["securities", "search", term],
    queryFn: ({ signal }) => searchSecurities(term, { init: { signal } }),
    enabled: term.length >= MIN_SEARCH_LENGTH,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

/** Price history for a ticker over a range button. `MAX` sends no `start`. */
export function usePriceHistory(ticker: string, range: RangeOption) {
  return useQuery<PriceHistoryResponse>({
    queryKey: ["securities", ticker, "prices", range],
    queryFn: ({ signal }) =>
      getSecurityPrices(ticker, { ...rangeToParams(range), init: { signal } }),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

/**
 * Risk & Return analytics for a ticker over a range button. Same `start`/`end`
 * mapping as `usePriceHistory`; `keepPreviousData` avoids a blank grid while a
 * new range loads, and the query key (including `range`) plus the request's
 * `AbortSignal` mean a stale in-flight response for an abandoned range is
 * never applied.
 */
export function useSecurityAnalytics(ticker: string, range: RangeOption) {
  return useQuery<AnalyticsResponse>({
    queryKey: ["securities", ticker, "analytics", range],
    queryFn: ({ signal }) =>
      getSecurityAnalytics(ticker, { ...rangeToParams(range), init: { signal } }),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}
