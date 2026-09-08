"use client";

import { useState } from "react";

import { MAX_COMPARISON_TICKERS, MIN_COMPARISON_TICKERS } from "@/lib/api/comparison";
import { useComparison } from "@/lib/api/hooks";
import type { CorrelationMatrix, SecurityRead } from "@/lib/api/types";
import { formatCorrelation, formatDate, RANGE_OPTIONS, type RangeOption } from "@/lib/format";
import { ComparisonChart } from "./ComparisonChart";
import { SecuritySearch } from "./SecuritySearch";

/**
 * Comparison tab: a ticker set (seeded with the current page's security) +
 * range controls + the base-100 normalized-performance chart + the
 * correlation matrix, all from one `GET /compare` response.
 *
 * The comparison endpoint requires 2-8 distinct tickers. With only the
 * seeded ticker selected, `useComparison`'s query is disabled (never fires,
 * never risks a 422) and this component renders an explicit empty state
 * instead - it does not auto-select a second security.
 */
export function ComparisonPanel({ ticker }: { ticker: string }) {
  const [tickers, setTickers] = useState<string[]>([ticker]);
  const [range, setRange] = useState<RangeOption>("1Y");

  const query = useComparison(tickers, range);
  const data = query.data;
  const belowMinimum = tickers.length < MIN_COMPARISON_TICKERS;
  const atMaximum = tickers.length >= MAX_COMPARISON_TICKERS;

  function addTicker(security: SecurityRead) {
    setTickers((prev) => (prev.includes(security.ticker) ? prev : [...prev, security.ticker]));
  }

  function removeTicker(t: string) {
    setTickers((prev) => prev.filter((x) => x !== t));
  }

  return (
    <section aria-label="Security comparison" data-testid="comparison-panel">
      <div className="qs-compare-tickers" role="list" aria-label="Selected securities">
        {tickers.map((t) => (
          <span key={t} role="listitem" className="qs-compare-chip">
            {t}
            <button
              type="button"
              className="qs-compare-chip__remove"
              aria-label={`Remove ${t}`}
              onClick={() => removeTicker(t)}
            >
              ×
            </button>
          </span>
        ))}
        {!atMaximum && (
          <div className="qs-compare-add">
            <SecuritySearch
              variant="bar"
              placeholder="Add security to compare"
              excludeTickers={tickers}
              onSelect={addTicker}
            />
          </div>
        )}
      </div>

      {belowMinimum ? (
        <div className="qs-empty" data-testid="comparison-empty-state">
          <div className="qs-empty__mark" aria-hidden />
          <div className="qs-empty__title">Add at least one security to compare</div>
          <div className="qs-empty__msg">
            Comparison needs 2-8 securities. Use the field above to add another ticker.
          </div>
        </div>
      ) : (
        <>
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
              <span className="qs-source" data-testid="comparison-source">
                Source: {data?.source ?? "—"} · Adjusted close
                {query.isPlaceholderData && (
                  <span className="qs-refreshing" data-testid="comparison-refreshing">
                    {" "}
                    · Refreshing…
                  </span>
                )}
              </span>
            </div>
          </div>

          {query.isLoading && (
            <div className="qs-skel" style={{ height: 420 }} aria-label="Loading comparison" />
          )}

          {query.isError && (
            <div className="qs-empty" role="alert">
              <div className="qs-empty__title">Comparison unavailable</div>
              <div className="qs-empty__msg">Couldn&rsquo;t load the comparison for these securities.</div>
              <div>
                <button type="button" className="qs-btn" style={{ marginTop: 16 }} onClick={() => query.refetch()}>
                  Retry
                </button>
              </div>
            </div>
          )}

          {query.isSuccess && data && data.status === "unavailable" && (
            <div className="qs-empty" data-testid="comparison-unavailable">
              <div className="qs-empty__title">Missing price history</div>
              <div className="qs-empty__msg">
                No comparison could be run: {(data.unavailable_tickers ?? []).join(", ")}{" "}
                {(data.unavailable_tickers ?? []).length === 1 ? "has" : "have"} no persisted price
                history for source {data.source}.
              </div>
            </div>
          )}

          {query.isSuccess && data && data.status === "insufficient_observations" && (
            <div className="qs-empty" data-testid="comparison-insufficient">
              <div className="qs-empty__title">Not enough overlapping history</div>
              <div className="qs-empty__msg">
                {data.observations_used ?? 0} / {data.required ?? "—"} aligned observations. Try a wider
                range or a different set of securities.
              </div>
            </div>
          )}

          {query.isSuccess && data && data.status === "ok" && data.normalized_performance && (
            <div className={query.isPlaceholderData ? "qs-stale" : undefined}>
              <div className="qs-analytics__meta" data-testid="comparison-meta">
                {formatDate(data.aligned_start)} – {formatDate(data.aligned_end)} · {data.observations_used}{" "}
                observations
              </div>

              <div className="qs-chart">
                <ComparisonChart normalized={data.normalized_performance} />
              </div>

              {data.correlation && (
                <CorrelationTable
                  correlation={data.correlation}
                  zeroVarianceTickers={data.zero_variance_tickers}
                />
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function CorrelationTable({
  correlation,
  zeroVarianceTickers,
}: {
  correlation: CorrelationMatrix;
  zeroVarianceTickers: string[] | null;
}) {
  return (
    <div className="qs-corr" data-testid="correlation-matrix">
      <div className="qs-corr__title">Correlation</div>
      <div style={{ overflowX: "auto" }}>
        <table className="qs-corr-table">
          <thead>
            <tr>
              <th />
              {correlation.tickers.map((t) => (
                <th key={t}>{t}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {correlation.tickers.map((rowTicker, ri) => (
              <tr key={rowTicker}>
                <th>{rowTicker}</th>
                {correlation.matrix[ri].map((cell, ci) => (
                  <td key={ci} className={ri === ci ? "qs-corr-table__diag" : undefined}>
                    {formatCorrelation(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {zeroVarianceTickers && zeroVarianceTickers.length > 0 && (
        <div className="qs-corr__note">
          Undefined for zero-variance ticker(s): {zeroVarianceTickers.join(", ")}
        </div>
      )}
    </div>
  );
}
