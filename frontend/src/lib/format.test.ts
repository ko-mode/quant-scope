import { describe, expect, it } from "vitest";

import type { PriceBar } from "./api/types";
import {
  assetTypeLabel,
  emptyStateFor,
  formatAxisDate,
  rangeToParams,
  securityHref,
  statusLabel,
  toPriceSeries,
} from "./format";

const bar = (over: Partial<PriceBar>): PriceBar => ({
  trade_date: "2024-01-02",
  open: null,
  high: null,
  low: null,
  close: 100,
  adj_close: 95,
  volume: null,
  source: "tiingo",
  ...over,
});

describe("rangeToParams", () => {
  const today = new Date("2026-06-15T00:00:00Z");

  it("1Y/3Y/5Y subtract whole years and omit end", () => {
    expect(rangeToParams("1Y", today)).toEqual({ start: "2025-06-15" });
    expect(rangeToParams("3Y", today)).toEqual({ start: "2023-06-15" });
    expect(rangeToParams("5Y", today)).toEqual({ start: "2021-06-15" });
  });

  it("MAX sends no start", () => {
    expect(rangeToParams("MAX", today)).toEqual({});
  });
});

describe("toPriceSeries", () => {
  it("plots adj_close, not raw close, preserving order", () => {
    const bars = [
      bar({ trade_date: "2024-01-02", close: 200, adj_close: 190 }),
      bar({ trade_date: "2024-01-03", close: 210, adj_close: 199 }),
    ];
    expect(toPriceSeries(bars)).toEqual([
      { time: "2024-01-02", value: 190 },
      { time: "2024-01-03", value: 199 },
    ]);
  });

  it("handles an empty history", () => {
    expect(toPriceSeries([])).toEqual([]);
  });
});

describe("securityHref", () => {
  it("normalises to an uppercase /securities/{ticker} path", () => {
    expect(securityHref(" nvda ")).toBe("/securities/NVDA");
  });
});

describe("assetTypeLabel / statusLabel", () => {
  it("maps known asset types and null", () => {
    expect(assetTypeLabel("common_stock")).toBe("Common stock");
    expect(assetTypeLabel("etf")).toBe("ETF");
    expect(assetTypeLabel(null)).toBe("—");
  });

  it("labels status from is_active / delisted_date", () => {
    expect(statusLabel({ is_active: true, delisted_date: null })).toBe("Active");
    expect(statusLabel({ is_active: false, delisted_date: "2023-03-10" })).toBe(
      "Inactive · delisted 2023-03-10",
    );
  });
});

describe("formatAxisDate", () => {
  it("renders a compact month-year label", () => {
    expect(formatAxisDate("2024-06-10")).toBe("Jun '24");
  });
});

describe("emptyStateFor", () => {
  it("MAX empty => nothing ingested", () => {
    expect(emptyStateFor("MAX").title).toBe("No price history available");
  });

  it("narrower empty => points at MAX without claiming history exists", () => {
    const state = emptyStateFor("3Y");
    expect(state.message).toMatch(/try max/i);
    expect(state.message).toMatch(/no observations available in this range/i);
    // must not assert the security has price history Phase 1E can't confirm
    expect(state.message).not.toMatch(/has price history/i);
    expect(state.message).not.toMatch(/full available history/i);
  });
});
