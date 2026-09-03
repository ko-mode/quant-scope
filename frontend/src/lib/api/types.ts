/**
 * TypeScript mirror of the Phase 1E read-only API response models
 * (`backend/src/quantscope/api/schemas.py`). Hand-written for three endpoints;
 * a generated client from the OpenAPI schema can replace this later.
 *
 * Price fields are JSON **numbers** (the Phase 1E contract), never strings.
 */

export type PriceSource = "tiingo" | "stooq";

export interface SecurityRead {
  ticker: string;
  name: string;
  exchange: string;
  currency: string;
  asset_type: string | null;
  is_active: boolean;
  first_trade_date: string | null;
  last_trade_date: string | null;
  delisted_date: string | null;
}

export interface SecurityListResponse {
  results: SecurityRead[];
  limit: number;
  offset: number;
  /** Rows in this page, not a universe-wide match total. */
  count: number;
}

export interface PriceBar {
  trade_date: string; // ISO date, YYYY-MM-DD
  open: number | null;
  high: number | null;
  low: number | null;
  close: number; // raw as-traded close
  adj_close: number; // vendor split+dividend adjusted (the V1 total-return series)
  volume: number | null;
  source: string;
}

export interface PriceHistoryResponse {
  ticker: string;
  /** The resolved source (defaulted from the backend price provider when omitted). */
  source: string;
  start: string | null;
  end: string | null;
  limit: number;
  offset: number;
  count: number;
  results: PriceBar[];
}
