"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { rangeToParams, type RangeOption } from "@/lib/format";
import { getSecurityPrices, MIN_SEARCH_LENGTH, searchSecurities } from "./securities";
import type { PriceHistoryResponse, SecurityListResponse } from "./types";

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
