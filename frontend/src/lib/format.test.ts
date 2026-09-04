import { describe, expect, it } from "vitest";

import type { PriceBar } from "./api/types";
import {
  analyticsRangeLabel,
  assetTypeLabel,
  emptyStateFor,
  formatAxisDate,
  formatPercent,
  formatRatio,
  observationsFraction,
  rangeToParams,
  securityHref,
  statusLabel,
  toPriceSeries,
  unavailableReasonLabel,
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

describe("formatPercent", () => {
  it("multiplies by 100 and fixes decimals, without altering sign", () => {
    expect(formatPercent(0.184)).toBe("18.40%");
    expect(formatPercent(-0.221)).toBe("-22.10%");
    expect(formatPercent(0)).toBe("0.00%");
  });

  it("preserves the backend's positive-loss VaR convention (no sign flip)", () => {
    // ADR 0017: VaR/ES are positive loss magnitudes - formatting must not negate them.
    expect(formatPercent(0.0416)).toBe("4.16%");
  });

  it("renders null/undefined/NaN as an em dash", () => {
    expect(formatPercent(null)).toBe("—");
    expect(formatPercent(undefined)).toBe("—");
    expect(formatPercent(Number.NaN)).toBe("—");
  });
});

describe("formatRatio", () => {
  it("fixes decimals for ratio metrics (Sharpe, beta)", () => {
    expect(formatRatio(1.4231)).toBe("1.42");
    expect(formatRatio(-0.5)).toBe("-0.50");
  });

  it("renders null as an em dash", () => {
    expect(formatRatio(null)).toBe("—");
  });
});

describe("observationsFraction", () => {
  it("renders 'used / required observations'", () => {
    expect(observationsFraction(52, 126)).toBe("52 / 126 observations");
  });

  it("renders nothing when either value is missing", () => {
    expect(observationsFraction(null, 126)).toBe("");
    expect(observationsFraction(52, null)).toBe("");
  });
});

describe("unavailableReasonLabel", () => {
  it("maps known reason codes to a short human label", () => {
    expect(unavailableReasonLabel("risk_free_series_not_ingested")).toBe("RF not ingested");
    expect(unavailableReasonLabel("benchmark_security_not_found")).toBe("SPY benchmark unavailable");
    expect(unavailableReasonLabel("benchmark_price_history_unavailable")).toBe(
      "Benchmark history unavailable",
    );
  });

  it("de-slugs an unrecognised code rather than hiding it", () => {
    expect(unavailableReasonLabel("some_future_reason")).toBe("some future reason");
  });

  it("falls back to a generic label when there is no reason", () => {
    expect(unavailableReasonLabel(null)).toBe("Unavailable");
  });
});

describe("analyticsRangeLabel", () => {
  it("renders the return-observation date span and count", () => {
    expect(
      analyticsRangeLabel({
        analytics_start: "2022-01-04",
        analytics_end: "2022-12-30",
        return_observations: 204,
      }),
    ).toBe("Jan 4, 2022 – Dec 30, 2022 · 204 observations");
  });

  it("renders just the count when no return series could be formed", () => {
    expect(
      analyticsRangeLabel({ analytics_start: null, analytics_end: null, return_observations: 0 }),
    ).toBe("0 observations");
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
