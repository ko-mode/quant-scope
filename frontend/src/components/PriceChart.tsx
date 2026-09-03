"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { PriceBar } from "@/lib/api/types";
import { CHART_HEIGHT, computeChartGeometry, nearestIndex } from "@/lib/chart";

/**
 * Adjusted-close line chart, hand-drawn SVG (matches the approved design).
 * Primary line = `adj_close`; raw `close` is an optional dashed overlay shown
 * only when `showRaw`. Crosshair + dark tooltip on hover. No analytics.
 */
export function PriceChart({ bars, showRaw }: { bars: PriceBar[]; showRaw: boolean }) {
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

  useEffect(() => setHoverIndex(null), [bars, showRaw]);

  const geo = useMemo(
    () => computeChartGeometry(bars, { width, showRaw, hoverIndex }),
    [bars, width, showRaw, hoverIndex],
  );

  function onMove(event: React.MouseEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * geo.width;
    setHoverIndex(nearestIndex(geo.xs, x));
  }

  const label = bars.length
    ? `Adjusted close price, ${bars[0].trade_date} to ${bars[bars.length - 1].trade_date}, ${bars.length} points`
    : "Adjusted close price chart";

  return (
    <div ref={wrapRef} style={{ position: "relative" }}>
      <svg
        viewBox={`0 0 ${geo.width} ${CHART_HEIGHT}`}
        width="100%"
        height={CHART_HEIGHT}
        role="img"
        aria-label={label}
        onMouseMove={onMove}
        onMouseLeave={() => setHoverIndex(null)}
        style={{ overflow: "visible" }}
      >
        {geo.yTicks.map((t, i) => (
          <g key={i}>
            <line
              x1={8}
              x2={geo.gridRight}
              y1={t.y}
              y2={t.y}
              stroke="oklch(93% 0.003 250)"
              strokeWidth={1}
            />
            <text
              x={geo.gridRight + 10}
              y={t.y}
              dy={3.5}
              fontFamily="var(--font-mono)"
              fontSize={10.5}
              fill="oklch(55% 0.008 255)"
            >
              {t.label}
            </text>
          </g>
        ))}

        <path d={geo.areaPath} fill="oklch(47% 0.15 241 / 0.06)" stroke="none" />
        {geo.rawPath && (
          <path
            d={geo.rawPath}
            fill="none"
            stroke="oklch(65% 0.01 255)"
            strokeWidth={1.25}
            strokeDasharray="3,3"
          />
        )}
        <path d={geo.linePath} fill="none" stroke="oklch(47% 0.15 241)" strokeWidth={1.75} />

        {geo.xTicks.map((t, i) => (
          <text
            key={i}
            x={t.x}
            y={CHART_HEIGHT - 16}
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
              y2={CHART_HEIGHT - 40}
              stroke="oklch(60% 0.01 255)"
              strokeWidth={1}
              strokeDasharray="2,3"
            />
            <circle
              cx={geo.hover.x}
              cy={geo.hover.y}
              r={3.5}
              fill="oklch(47% 0.15 241)"
              stroke="#fff"
              strokeWidth={1.5}
            />
          </g>
        )}
      </svg>

      {geo.hover && (
        <div
          className="qs-chart__tooltip"
          style={{
            left: `${geo.hover.leftPct}%`,
            transform: geo.hover.tooltipTransform,
          }}
        >
          <div>{geo.hover.date}</div>
          <div className="dim">
            Adj close <strong style={{ color: "var(--bg)", fontWeight: 600 }}>{geo.hover.adjClose}</strong>
          </div>
          {geo.hover.rawClose && (
            <div className="dim">
              Raw close <span style={{ color: "var(--bg)" }}>{geo.hover.rawClose}</span>
            </div>
          )}
          <div className="dim">
            Volume <span style={{ color: "var(--bg)" }}>{geo.hover.volume}</span>
          </div>
        </div>
      )}
    </div>
  );
}
