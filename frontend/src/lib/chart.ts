/**
 * Pure SVG geometry for the price chart. No React, no DOM - unit-tested.
 *
 * The primary line is **`adj_close`** (V1 total-return convention). Raw `close`
 * is an optional secondary series the caller renders as a dashed overlay; it is
 * never the primary line and no returns are computed here.
 */

import type { PriceBar } from "./api/types";
import { formatAxisDate, formatDate, formatPrice, formatVolume } from "./format";

export const CHART_HEIGHT = 480;
const PAD = { left: 8, right: 66, top: 18, bottom: 40 };
const Y_TICKS = 5;
const X_TICKS = 6;

export interface ChartPoint {
  x: number;
  y: number;
}

export interface ChartHover {
  index: number;
  x: number;
  y: number;
  leftPct: number;
  tooltipTransform: string;
  date: string;
  adjClose: string;
  rawClose: string | null;
  volume: string;
}

export interface ChartGeometry {
  width: number;
  height: number;
  gridRight: number;
  /** x pixel for each bar index - lets the caller map a cursor to the nearest bar. */
  xs: number[];
  linePath: string;
  areaPath: string;
  /** Present only when `showRaw` and every bar has a raw close. */
  rawPath: string | null;
  yTicks: Array<{ y: number; label: string }>;
  xTicks: Array<{ x: number; label: string }>;
  hover: ChartHover | null;
}

function pathFrom(points: ChartPoint[]): string {
  return points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" ");
}

export interface GeometryOptions {
  width: number;
  height?: number;
  showRaw?: boolean;
  hoverIndex?: number | null;
}

export function computeChartGeometry(
  bars: readonly PriceBar[],
  { width, height = CHART_HEIGHT, showRaw = false, hoverIndex = null }: GeometryOptions,
): ChartGeometry {
  const gridRight = width - PAD.right;
  const innerW = Math.max(1, width - PAD.left - PAD.right);
  const innerH = Math.max(1, height - PAD.top - PAD.bottom);

  const rawUsable = showRaw && bars.length > 0 && bars.every((b) => typeof b.close === "number");

  const empty: ChartGeometry = {
    width,
    height,
    gridRight,
    xs: [],
    linePath: "",
    areaPath: "",
    rawPath: null,
    yTicks: [],
    xTicks: [],
    hover: null,
  };
  if (bars.length === 0) return empty;

  const adj = bars.map((b) => b.adj_close);
  const raw = rawUsable ? bars.map((b) => b.close) : [];
  const domain = adj.concat(raw);
  let yMin = Math.min(...domain);
  let yMax = Math.max(...domain);
  const pad = (yMax - yMin) * 0.08 || Math.max(1, yMax * 0.08);
  yMin -= pad;
  yMax += pad;

  const xStep = innerW / Math.max(1, bars.length - 1);
  const xAt = (i: number) => PAD.left + i * xStep;
  const yAt = (v: number) => PAD.top + innerH - ((v - yMin) / (yMax - yMin || 1)) * innerH;

  const xs = bars.map((_, i) => xAt(i));
  const linePts = bars.map((b, i) => ({ x: xAt(i), y: yAt(b.adj_close) }));
  const linePath = pathFrom(linePts);

  const baseline = PAD.top + innerH;
  const areaPath =
    `M${linePts[0].x.toFixed(2)},${baseline.toFixed(2)} ` +
    linePts.map((p) => `L${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" ") +
    ` L${linePts[linePts.length - 1].x.toFixed(2)},${baseline.toFixed(2)} Z`;

  const rawPath = rawUsable ? pathFrom(bars.map((b, i) => ({ x: xAt(i), y: yAt(b.close as number) }))) : null;

  const yTicks = Array.from({ length: Y_TICKS }, (_, i) => {
    const v = yMin + ((yMax - yMin) * i) / (Y_TICKS - 1);
    return { y: yAt(v), label: formatPrice(v) };
  });

  const xTickCount = Math.min(X_TICKS, bars.length);
  const xTicks = Array.from({ length: xTickCount }, (_, i) => {
    const idx = Math.round(((bars.length - 1) * i) / Math.max(1, xTickCount - 1));
    return { x: xAt(idx), label: formatAxisDate(bars[idx].trade_date) };
  });

  let hover: ChartHover | null = null;
  if (hoverIndex != null && hoverIndex >= 0 && hoverIndex < bars.length) {
    const b = bars[hoverIndex];
    const x = xAt(hoverIndex);
    const leftPct = (x / width) * 100;
    hover = {
      index: hoverIndex,
      x,
      y: yAt(b.adj_close),
      leftPct,
      tooltipTransform:
        leftPct > 78 ? "translateX(-100%)" : leftPct < 8 ? "translateX(0)" : "translateX(-50%)",
      date: formatDate(b.trade_date),
      adjClose: formatPrice(b.adj_close),
      rawClose: rawUsable ? formatPrice(b.close) : null,
      volume: formatVolume(b.volume),
    };
  }

  return { width, height, gridRight, xs, linePath, areaPath, rawPath, yTicks, xTicks, hover };
}

/** Nearest bar index to a cursor x (in the same pixel space as `geometry.xs`). */
export function nearestIndex(xs: readonly number[], cursorX: number): number {
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
