"use client";

import { useState } from "react";

import { useSecurityAnalytics } from "@/lib/api/hooks";
import type { AnalyticsResponse, MetricStatus } from "@/lib/api/types";
import {
  analyticsRangeLabel,
  formatPercent,
  formatRatio,
  observationsFraction,
  RANGE_OPTIONS,
  unavailableReasonLabel,
  type RangeOption,
} from "@/lib/format";

/**
 * Risk & Return tab: range controls (own state, independent of the Price
 * tab - Phase 2C decision) + the analytics metrics grid + a methodology
 * footer built from the response's own `assumptions` block.
 *
 * This component performs **no financial computation**. It only requests
 * `GET /securities/{ticker}/analytics`, formats the values it gets back, and
 * renders each metric's `status` distinctly. A `null` value under a
 * non-`"ok"` status is never displayed as `0`.
 */
export function RiskReturnPanel({ ticker }: { ticker: string }) {
  const [range, setRange] = useState<RangeOption>("1Y");
  const query = useSecurityAnalytics(ticker, range);
  const analytics = query.data;

  return (
    <section aria-label="Risk and return analytics" data-testid="risk-return-panel">
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
          <span className="qs-source" data-testid="analytics-source">
            Source: {analytics?.source ?? "—"} · Adjusted close
          </span>
        </div>
      </div>

      <div className="qs-analytics">
        {query.isLoading && (
          <div className="qs-skel" style={{ height: 240 }} aria-label="Loading risk and return analytics" />
        )}

        {query.isError && (
          <div className="qs-empty" role="alert">
            <div className="qs-empty__title">Risk &amp; return analytics unavailable</div>
            <div className="qs-empty__msg">Couldn&rsquo;t load analytics for this security.</div>
            <div>
              <button type="button" className="qs-btn" style={{ marginTop: 16 }} onClick={() => query.refetch()}>
                Retry
              </button>
            </div>
          </div>
        )}

        {query.isSuccess && analytics && (
          <>
            <div className="qs-analytics__meta" data-testid="analytics-meta">
              {analyticsRangeLabel(analytics)}
            </div>

            <div className="qs-metrics-grid">
              {buildMetricCells(analytics).map((cell) => (
                <MetricCard key={cell.key} cell={cell} />
              ))}
            </div>

            <p className="qs-methodology" data-testid="methodology">
              {methodologyText(analytics)}
            </p>
          </>
        )}
      </div>
    </section>
  );
}

interface MetricCell {
  key: string;
  label: string;
  status: MetricStatus;
  value: string;
  note: string;
  reason: string | null;
  observationsUsed: number | null;
  required: number | null;
  loss?: boolean;
}

function buildMetricCells(analytics: AnalyticsResponse): MetricCell[] {
  const { return_summary, volatility, sharpe, beta, drawdown, var_es_95, var_es_99 } = analytics;
  return [
    {
      key: "cumulative_return",
      label: "Cumulative return",
      status: return_summary.status,
      value: formatPercent(return_summary.cumulative_return),
      note: "Selected range",
      reason: return_summary.reason,
      observationsUsed: return_summary.observations_used,
      required: return_summary.required,
    },
    {
      key: "annualised_volatility",
      label: "Annualized volatility",
      status: volatility.status,
      value: formatPercent(volatility.annualised_volatility),
      note: "Daily × √252",
      reason: volatility.reason,
      observationsUsed: volatility.observations_used,
      required: volatility.required,
    },
    {
      key: "sharpe_ratio",
      label: "Sharpe ratio",
      status: sharpe.status,
      value: formatRatio(sharpe.sharpe_ratio),
      note: "Daily excess return, Kenneth French RF",
      reason: sharpe.reason,
      observationsUsed: sharpe.observations_used,
      required: sharpe.required,
    },
    {
      key: "beta",
      label: "Beta vs SPY",
      status: beta.status,
      value: formatRatio(beta.beta),
      note: "OLS, daily excess returns",
      reason: beta.reason,
      observationsUsed: beta.observations_used,
      required: beta.required,
    },
    {
      key: "max_drawdown",
      label: "Max drawdown",
      status: drawdown.status,
      value: formatPercent(drawdown.max_drawdown),
      note: "Peak to trough",
      reason: drawdown.reason,
      observationsUsed: drawdown.observations_used,
      required: drawdown.required,
      loss: true,
    },
    {
      key: "var_95",
      label: "VaR 95%",
      status: var_es_95.status,
      value: formatPercent(var_es_95.var),
      note: "1-day, historical",
      reason: var_es_95.reason,
      observationsUsed: var_es_95.observations_used,
      required: var_es_95.required,
    },
    {
      key: "es_95",
      label: "ES 95%",
      status: var_es_95.status,
      value: formatPercent(var_es_95.expected_shortfall),
      note: "Mean of tail beyond VaR",
      reason: var_es_95.reason,
      observationsUsed: var_es_95.observations_used,
      required: var_es_95.required,
    },
    {
      key: "var_99",
      label: "VaR 99%",
      status: var_es_99.status,
      value: formatPercent(var_es_99.var),
      note: "1-day, historical",
      reason: var_es_99.reason,
      observationsUsed: var_es_99.observations_used,
      required: var_es_99.required,
    },
    {
      key: "es_99",
      label: "ES 99%",
      status: var_es_99.status,
      value: formatPercent(var_es_99.expected_shortfall),
      note: "Mean of tail beyond VaR",
      reason: var_es_99.reason,
      observationsUsed: var_es_99.observations_used,
      required: var_es_99.required,
    },
  ];
}

function MetricCard({ cell }: { cell: MetricCell }) {
  return (
    <div className="qs-metric" data-testid={`metric-${cell.key}`}>
      <div className="qs-metric__label">{cell.label}</div>
      <MetricBody cell={cell} />
    </div>
  );
}

function MetricBody({ cell }: { cell: MetricCell }) {
  if (cell.status === "ok") {
    return (
      <>
        <div className={cell.loss ? "qs-metric__value qs-metric__value--loss" : "qs-metric__value"}>
          {cell.value}
        </div>
        <div className="qs-metric__note">{cell.note}</div>
      </>
    );
  }
  if (cell.status === "insufficient_observations") {
    return (
      <>
        <div className="qs-metric__status qs-metric__status--insufficient">Insufficient data</div>
        <div className="qs-metric__note">
          {observationsFraction(cell.observationsUsed, cell.required)}
        </div>
      </>
    );
  }
  if (cell.status === "undefined") {
    return (
      <>
        <div className="qs-metric__status qs-metric__status--undefined">Undefined</div>
        {cell.reason && <div className="qs-metric__note">{cell.reason}</div>}
      </>
    );
  }
  return (
    <>
      <div className="qs-metric__status qs-metric__status--unavailable">Unavailable</div>
      <div className="qs-metric__note">{unavailableReasonLabel(cell.reason)}</div>
    </>
  );
}

/** Built entirely from `assumptions` - no hard-coded methodology claims. */
function methodologyText(analytics: AnalyticsResponse): string {
  const a = analytics.assumptions;
  const rfClause =
    a.rf_basis === "daily_series" ? "Kenneth French daily RF" : "risk-free series not ingested";
  return (
    `Computed from persisted adjusted-close daily returns (${a.calendar}), annualized ×${a.annualisation_factor}. ` +
    `Sharpe: ${rfClause}. Beta: OLS vs ${a.benchmark} daily excess returns, same RF series. ` +
    `VaR / ES: ${a.var_horizon_days}-day historical, no scaling. Source: ${analytics.source} · Adjusted close.`
  );
}
