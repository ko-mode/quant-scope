import { describe, expect, it } from "vitest";

import type { NormalizedPerformance } from "./api/types";
import { computeComparisonGeometry, nearestComparisonIndex } from "./comparisonChart";

const SAMPLE: NormalizedPerformance = {
  base_value: 100,
  dates: [null, "2024-01-02", "2024-02-01", "2024-03-01"],
  series: {
    AAPL: [100, 105, 98, 112],
    MSFT: [100, 101, 99, 103],
  },
};

describe("computeComparisonGeometry", () => {
  it("returns an empty geometry when there is no normalized performance", () => {
    const g = computeComparisonGeometry(null, { width: 1000 });
    expect(g.series).toEqual([]);
    expect(g.xs).toEqual([]);
    expect(g.hover).toBeNull();
  });

  it("draws one line per ticker, in series order (not alphabetical)", () => {
    const g = computeComparisonGeometry(SAMPLE, { width: 1000 });
    expect(g.series.map((s) => s.ticker)).toEqual(["AAPL", "MSFT"]);
    expect(g.series[0].linePath).toMatch(/^M/);
    expect(g.series[0].linePath.match(/[ML]/g)).toHaveLength(4); // anchor + 3 returns
  });

  it("assigns a stable colour per series index", () => {
    const g = computeComparisonGeometry(SAMPLE, { width: 1000 });
    expect(g.series[0].color).not.toBe(g.series[1].color);
  });

  it("the anchor (index 0) x-tick is labelled 'Start', not a fabricated date", () => {
    const g = computeComparisonGeometry(SAMPLE, { width: 1000 });
    expect(g.xTicks[0].label).toBe("Start");
  });

  it("builds a hover payload with every ticker's value at that index", () => {
    const g = computeComparisonGeometry(SAMPLE, { width: 1000, hoverIndex: 1 });
    expect(g.hover?.index).toBe(1);
    expect(g.hover?.date).toBe("Jan '24");
    expect(g.hover?.values).toEqual([
      { ticker: "AAPL", color: g.series[0].color, value: "105.00", y: expect.any(Number) },
      { ticker: "MSFT", color: g.series[1].color, value: "101.00", y: expect.any(Number) },
    ]);
  });

  it("hovering the anchor (index 0) shows 'Start' with base-100 values", () => {
    const g = computeComparisonGeometry(SAMPLE, { width: 1000, hoverIndex: 0 });
    expect(g.hover?.date).toBe("Start");
    expect(g.hover?.values.every((v) => v.value === "100.00")).toBe(true);
  });

  it("ignores an out-of-range hover index", () => {
    expect(computeComparisonGeometry(SAMPLE, { width: 1000, hoverIndex: 99 }).hover).toBeNull();
    expect(computeComparisonGeometry(SAMPLE, { width: 1000, hoverIndex: -1 }).hover).toBeNull();
  });
});

describe("nearestComparisonIndex", () => {
  it("finds the closest x", () => {
    expect(nearestComparisonIndex([0, 100, 200, 300], 170)).toBe(2);
    expect(nearestComparisonIndex([0, 100, 200, 300], -5)).toBe(0);
    expect(nearestComparisonIndex([], 10)).toBe(-1);
  });
});
