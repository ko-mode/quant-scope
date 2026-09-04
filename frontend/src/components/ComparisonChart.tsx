"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { NormalizedPerformance } from "@/lib/api/types";
import {
  COMPARISON_CHART_HEIGHT,
  computeComparisonGeometry,
  nearestComparisonIndex,
} from "@/lib/comparisonChart";

/**
 * Base-100 normalized-performance line chart, one line per ticker, hand-drawn
 * SVG (matches `PriceChart`'s pattern). No analytics happens here - every
 * value is already the API's chosen wealth-index convention.
 */
export function ComparisonChart({ normalized }: { normalized: NormalizedPerformance }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(1000);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0].contentRect.width);
      if (w > 0) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => setHoverIndex(null), [normalized]);

  const geo = useMemo(
    () => computeComparisonGeometry(normalized, { width, hoverIndex }),
    [normalized, width, hoverIndex],
  );

  function onMove(event: React.MouseEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * geo.width;
    setHoverIndex(nearestComparisonIndex(geo.xs, x));
  }

  const label = `Normalized performance, base 100, ${geo.series.length} securities`;

  return (
    <div ref={wrapRef} style={{ position: "relative" }}>
      <svg
        viewBox={`0 0 ${geo.width} ${COMPARISON_CHART_HEIGHT}`}
        width="100%"
        height={COMPARISON_CHART_HEIGHT}
        role="img"
        aria-label={label}
        onMouseMove={onMove}
        onMouseLeave={() => setHoverIndex(null)}
        style={{ overflow: "visible" }}
      >
        {geo.yTicks.map((t, i) => (
          <g key={i}>
            <line x1={8} x2={geo.gridRight} y1={t.y} y2={t.y} stroke="oklch(93% 0.003 250)" strokeWidth={1} />
            <text
              x={8}
              y={t.y}
              dy={-3}
              fontFamily="var(--font-mono)"
              fontSize={10.5}
              fill="oklch(55% 0.008 255)"
            >
              {t.label}
            </text>
          </g>
        ))}

        {geo.series.map((s) => (
          <path key={s.ticker} d={s.linePath} fill="none" stroke={s.color} strokeWidth={1.75} />
        ))}

        {geo.xTicks.map((t, i) => (
          <text
            key={i}
            x={t.x}
            y={COMPARISON_CHART_HEIGHT - 10}
            fontFamily="var(--font-mono)"
            fontSize={10.5}
            fill="oklch(55% 0.008 255)"
            textAnchor="middle"
          >
            {t.label}
          </text>
        ))}

        {geo.hover && (
          <g>
            <line
              x1={geo.hover.x}
              x2={geo.hover.x}
              y1={18}
              y2={COMPARISON_CHART_HEIGHT - 32}
              stroke="oklch(60% 0.01 255)"
              strokeWidth={1}
              strokeDasharray="2,3"
            />
            {geo.hover.values.map((v) => (
              <circle key={v.ticker} cx={geo.hover!.x} cy={v.y} r={3.5} fill={v.color} stroke="#fff" strokeWidth={1.5} />
            ))}
          </g>
        )}
      </svg>

      <div className="qs-compare-legend" role="list" aria-label="Series legend">
        {geo.series.map((s) => (
          <span key={s.ticker} role="listitem" className="qs-compare-legend__item">
            <span className="qs-compare-legend__swatch" style={{ background: s.color }} />
            {s.ticker}
          </span>
        ))}
      </div>

      {geo.hover && (
        <div
          className="qs-chart__tooltip"
          style={{ left: `${geo.hover.leftPct}%`, transform: geo.hover.tooltipTransform }}
        >
          <div>{geo.hover.date}</div>
          {geo.hover.values.map((v) => (
            <div className="dim" key={v.ticker}>
              <span style={{ color: v.color }}>{v.ticker}</span>{" "}
              <strong style={{ color: "var(--bg)", fontWeight: 600 }}>{v.value}</strong>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
