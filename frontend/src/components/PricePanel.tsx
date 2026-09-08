"use client";

import { useState } from "react";

import { usePriceHistory } from "@/lib/api/hooks";
import { emptyStateFor, RANGE_OPTIONS, type RangeOption } from "@/lib/format";
import { PriceChart } from "./PriceChart";

/**
 * Range controls + provenance + the price chart. Data comes from
 * `GET /securities/{ticker}/prices` for one range at a time; the resolved
 * `source` is shown, and series from different providers are never merged
 * (single-source query, Phase 1E guarantee).
 */
export function PricePanel({ ticker }: { ticker: string }) {
  const [range, setRange] = useState<RangeOption>("1Y");
  const [showRaw, setShowRaw] = useState(false);

  const query = usePriceHistory(ticker, range);
  const bars = query.data?.results ?? [];
  const resolvedSource = query.data?.source ?? "—";

  return (
    <section aria-label="Price history">
      <div className="qs-controls">
        <div className="qs-ranges" role="group" aria-label="Date range">
          {RANGE_OPTIONS.map((option) => (
            <button
              key={option}
              type="button"
              className="qs-range"
              aria-pressed={option === range}
              onClick={() => setRange(option)}
            >
              {option}
            </button>
          ))}
        </div>

        <div className="qs-controls__right">
          <label className="qs-rawtoggle">
            <input
              type="checkbox"
              checked={showRaw}
              onChange={(e) => setShowRaw(e.target.checked)}
            />
            Show raw close
          </label>
          <span className="qs-source" data-testid="price-source">
            Source: {resolvedSource} · Adjusted close
            {query.isPlaceholderData && (
              <span className="qs-refreshing" data-testid="price-refreshing">
                {" "}
                · Refreshing…
              </span>
            )}
          </span>
        </div>
      </div>

      <div className={query.isPlaceholderData ? "qs-chart qs-stale" : "qs-chart"}>
        {query.isLoading && <div className="qs-skel" style={{ height: 480 }} aria-label="Loading price history" />}

        {query.isError && (
          <div className="qs-empty" role="alert">
            <div className="qs-empty__title">Price history unavailable</div>
            <div className="qs-empty__msg">Couldn&rsquo;t load price data for this security.</div>
            <div>
              <button type="button" className="qs-btn" style={{ marginTop: 16 }} onClick={() => query.refetch()}>
                Retry
              </button>
            </div>
          </div>
        )}

        {query.isSuccess && bars.length === 0 && (
          <div className="qs-empty">
            <div className="qs-empty__mark" aria-hidden />
            <div className="qs-empty__title">{emptyStateFor(range).title}</div>
            <div className="qs-empty__msg">{emptyStateFor(range).message}</div>
          </div>
        )}

        {query.isSuccess && bars.length > 0 && <PriceChart bars={bars} showRaw={showRaw} />}
      </div>
    </section>
  );
}
