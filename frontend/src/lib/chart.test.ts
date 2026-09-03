import { describe, expect, it } from "vitest";

import type { PriceBar } from "./api/types";
import { computeChartGeometry, nearestIndex } from "./chart";

const bars = (values: Array<[string, number, number]>): PriceBar[] =>
  values.map(([trade_date, close, adj_close]) => ({
    trade_date,
    open: null,
    high: null,
    low: null,
    close,
    adj_close,
    volume: 1000,
    source: "tiingo",
  }));

const SAMPLE = bars([
  ["2024-01-02", 200, 100],
  ["2024-02-01", 210, 110],
  ["2024-03-01", 190, 90],
  ["2024-04-01", 230, 130],
]);

describe("computeChartGeometry", () => {
  it("returns an empty geometry for no bars", () => {
    const g = computeChartGeometry([], { width: 1000 });
    expect(g.linePath).toBe("");
    expect(g.xs).toEqual([]);
    expect(g.hover).toBeNull();
  });

  it("draws the line from adj_close (higher adj_close -> smaller y)", () => {
    const g = computeChartGeometry(SAMPLE, { width: 1000 });
    // 4 points in the path
    expect(g.linePath.match(/[ML]/g)).toHaveLength(4);
    expect(g.xs).toHaveLength(4);
    // adj_close peak (130, index 3) sits above the trough (90, index 2)
    const yAt = (i: number) =>
      Number(g.linePath.split(" ")[i].replace(/[ML]/, "").split(",")[1]);
    expect(yAt(3)).toBeLessThan(yAt(2));
  });

  it("omits the raw overlay unless showRaw and every bar has a numeric close", () => {
    expect(computeChartGeometry(SAMPLE, { width: 1000 }).rawPath).toBeNull();
    const withRaw = computeChartGeometry(SAMPLE, { width: 1000, showRaw: true });
    expect(withRaw.rawPath).toMatch(/^M/);
    // raw close (200-230) is far above adj_close (90-130): raw path differs from line path
    expect(withRaw.rawPath).not.toBe(withRaw.linePath);
  });

  it("produces 5 y ticks and at most 6 x ticks", () => {
    const g = computeChartGeometry(SAMPLE, { width: 1000 });
    expect(g.yTicks).toHaveLength(5);
    expect(g.xTicks.length).toBeLessThanOrEqual(6);
    expect(g.yTicks[0].label.startsWith("$")).toBe(true);
    expect(g.xTicks[0].label).toBe("Jan '24");
  });

  it("builds a hover payload with adj + raw + volume when hovering", () => {
    const g = computeChartGeometry(SAMPLE, { width: 1000, showRaw: true, hoverIndex: 1 });
    expect(g.hover?.index).toBe(1);
    expect(g.hover?.date).toBe("Feb 1, 2024");
    expect(g.hover?.adjClose).toBe("$110.00");
    expect(g.hover?.rawClose).toBe("$210.00");
    expect(g.hover?.volume).toBe("1,000");
  });

  it("ignores an out-of-range hover index", () => {
    expect(computeChartGeometry(SAMPLE, { width: 1000, hoverIndex: 99 }).hover).toBeNull();
    expect(computeChartGeometry(SAMPLE, { width: 1000, hoverIndex: -1 }).hover).toBeNull();
  });
});

describe("nearestIndex", () => {
  it("finds the closest x", () => {
    expect(nearestIndex([0, 100, 200, 300], 170)).toBe(2);
    expect(nearestIndex([0, 100, 200, 300], -5)).toBe(0);
    expect(nearestIndex([], 10)).toBe(-1);
  });
});
