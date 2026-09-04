/**
 * Pure SVG geometry for the Phase 3A normalized-performance chart. No React,
 * no DOM - unit-tested. One line per ticker over `NormalizedPerformance`
 * (already base-100, already the API's chosen anchor convention - this module
 * never re-normalizes or re-anchors anything it is given).
 */

import type { NormalizedPerformance } from "./api/types";
import { formatAxisDate, formatRatio } from "./format";

export const COMPARISON_CHART_HEIGHT = 420;
const PAD = { left: 8, right: 12, top: 18, bottom: 32 };
const Y_TICKS = 5;
const X_TICKS = 6;

/** Stable per-ticker colour, keyed by the ticker's position in the request
 * (not alphabetical), so a line's colour never shifts as data reloads. */
export const SERIES_COLORS = [
  "oklch(47% 0.15 241)", // accent blue
  "oklch(55% 0.16 25)", // red
  "oklch(55% 0.14 145)", // green
  "oklch(55% 0.15 300)", // purple
  "oklch(60% 0.15 70)", // orange
  "oklch(55% 0.12 200)", // teal
  "oklch(50% 0.14 350)", // pink
  "oklch(45% 0.02 255)", // slate
] as const;

export function colorFor(index: number): string {
  return SERIES_COLORS[index % SERIES_COLORS.length];
}

export interface ComparisonSeriesGeometry {
  ticker: string;
  color: string;
  linePath: string;
  lastY: number;
}

export interface ComparisonHover {
  index: number;
  x: number;
  leftPct: number;
  tooltipTransform: string;
  date: string;
  values: Array<{ ticker: string; color: string; value: string; y: number }>;
}

export interface ComparisonChartGeometry {
  width: number;
  height: number;
  gridRight: number;
  xs: number[];
  series: ComparisonSeriesGeometry[];
  yTicks: Array<{ y: number; label: string }>;
  xTicks: Array<{ x: number; label: string }>;
  hover: ComparisonHover | null;
}

export interface ComparisonGeometryOptions {
  width: number;
  height?: number;
  hoverIndex?: number | null;
}

/** "Start" for the null anchor date (index 0), otherwise the usual compact axis label. */
function axisLabel(date: string | null): string {
  return date == null ? "Start" : formatAxisDate(date);
}

export function computeComparisonGeometry(
  normalized: NormalizedPerformance | null | undefined,
  { width, height = COMPARISON_CHART_HEIGHT, hoverIndex = null }: ComparisonGeometryOptions,
): ComparisonChartGeometry {
  const gridRight = width - PAD.right;
  const innerW = Math.max(1, width - PAD.left - PAD.right);
  const innerH = Math.max(1, height - PAD.top - PAD.bottom);

  const empty: ComparisonChartGeometry = {
    width,
    height,
    gridRight,
    xs: [],
    series: [],
    yTicks: [],
    xTicks: [],
    hover: null,
  };

  const dates = normalized?.dates ?? [];
  const tickers = normalized ? Object.keys(normalized.series) : [];
  if (dates.length === 0 || tickers.length === 0) return empty;

  const allValues = tickers.flatMap((t) => normalized!.series[t]);
  let yMin = Math.min(...allValues);
  let yMax = Math.max(...allValues);
  const pad = (yMax - yMin) * 0.08 || Math.max(1, yMax * 0.08);
  yMin -= pad;
  yMax += pad;

  const xStep = innerW / Math.max(1, dates.length - 1);
  const xAt = (i: number) => PAD.left + i * xStep;
  const yAt = (v: number) => PAD.top + innerH - ((v - yMin) / (yMax - yMin || 1)) * innerH;

  const xs = dates.map((_, i) => xAt(i));

  const series: ComparisonSeriesGeometry[] = tickers.map((ticker, si) => {
    const values = normalized!.series[ticker];
    const points = values.map((v, i) => ({ x: xAt(i), y: yAt(v) }));
    const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" ");
    return { ticker, color: colorFor(si), linePath, lastY: points[points.length - 1].y };
  });

  const yTicks = Array.from({ length: Y_TICKS }, (_, i) => {
    const v = yMin + ((yMax - yMin) * i) / (Y_TICKS - 1);
    return { y: yAt(v), label: formatRatio(v, 0) };
  });

  const xTickCount = Math.min(X_TICKS, dates.length);
  const xTicks = Array.from({ length: xTickCount }, (_, i) => {
    const idx = Math.round(((dates.length - 1) * i) / Math.max(1, xTickCount - 1));
    return { x: xAt(idx), label: axisLabel(dates[idx]) };
  });

  let hover: ComparisonHover | null = null;
  if (hoverIndex != null && hoverIndex >= 0 && hoverIndex < dates.length) {
    const x = xAt(hoverIndex);
    const leftPct = (x / width) * 100;
    hover = {
      index: hoverIndex,
      x,
      leftPct,
      tooltipTransform:
        leftPct > 78 ? "translateX(-100%)" : leftPct < 8 ? "translateX(0)" : "translateX(-50%)",
      date: axisLabel(dates[hoverIndex]),
      values: tickers.map((ticker, si) => ({
        ticker,
        color: colorFor(si),
        value: formatRatio(normalized!.series[ticker][hoverIndex], 2),
        y: yAt(normalized!.series[ticker][hoverIndex]),
      })),
    };
  }

  return { width, height, gridRight, xs, series, yTicks, xTicks, hover };
}

/** Nearest index to a cursor x (same pixel space as `geometry.xs`). */
export function nearestComparisonIndex(xs: readonly number[], cursorX: number): number {
  if (xs.length === 0) return -1;
  let best = 0;
  let bestDist = Infinity;
  for (let i = 0; i < xs.length; i++) {
    const d = Math.abs(xs[i] - cursorX);
    if (d < bestDist) {
      bestDist = d;
      best = i;
    }
  }
  return best;
}
