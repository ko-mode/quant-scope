"use client";

import { useState } from "react";

import { useSecurityFactors } from "@/lib/api/hooks";
import type { FactorModelResult, RegressionCoefficient } from "@/lib/api/types";
import {
  formatDate,
  formatPercent,
  formatPValue,
  formatRatio,
  observationsFraction,
  RANGE_OPTIONS,
  unavailableReasonLabel,
  type RangeOption,
} from "@/lib/format";

const COEFFICIENT_LABEL: Record<string, string> = {
  alpha: "Alpha",
  spy_excess: "SPY excess return",
  mkt_rf: "Mkt-RF",
  smb: "SMB",
  hml: "HML",
};

function coefficientLabel(name: string): string {
  return COEFFICIENT_LABEL[name] ?? name;
}

/** Alpha is a tiny daily return, shown as a percentage; factor loadings are
 * dimensionless slopes, shown as plain ratios. Purely presentational - the
 * value itself is never recomputed or rescaled. */
function formatCoefficientValue(name: string, value: number | null): string {
  return name === "alpha" ? formatPercent(value, 4) : formatRatio(value, 3);
}

/**
 * Factors tab: range controls (own state, matching Risk & Return / Comparison)
 * + the SPY CAPM regression and Fama-French 3-factor regression, each with
 * its own status, plus a methodology footer built from the response's own
 * `assumptions` block.
 *
 * This component performs **no econometric computation**. It only requests
 * `GET /securities/{ticker}/factors`, formats the values it gets back, and
 * renders each model's `status` distinctly. A `null` inference field is
 * never displayed as `0`. There is no `alpha_annualized` anywhere - alpha is
 * always the daily regression intercept.
 */
export function FactorsPanel({ ticker }: { ticker: string }) {
  const [range, setRange] = useState<RangeOption>("1Y");
  const query = useSecurityFactors(ticker, range);
  const data = query.data;

  return (
    <section aria-label="Factor regressions" data-testid="factors-panel">
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
          <span className="qs-source" data-testid="factors-source">
            Source: {data?.source ?? "—"} · Adjusted close
          </span>
        </div>
      </div>

      {query.isLoading && (
        <div className="qs-skel" style={{ height: 360 }} aria-label="Loading factor regressions" />
      )}

      {query.isError && (
        <div className="qs-empty" role="alert">
          <div className="qs-empty__title">Factor regressions unavailable</div>
          <div className="qs-empty__msg">Couldn&rsquo;t load factor regressions for this security.</div>
          <div>
            <button type="button" className="qs-btn" style={{ marginTop: 16 }} onClick={() => query.refetch()}>
              Retry
            </button>
          </div>
        </div>
      )}

      {query.isSuccess && data && (
        <>
          <FactorModelSection id="capm" title="CAPM (vs SPY)" model={data.capm} />
          <FactorModelSection id="ff3" title="Fama-French 3-Factor" model={data.ff3} />

          <p className="qs-methodology" data-testid="factors-methodology">
            {data.assumptions.capm_vs_ff3_note} {data.assumptions.alpha_note} Newey-West lag rule:{" "}
            {data.assumptions.hac_lag_rule}.
          </p>
        </>
      )}
    </section>
  );
}

function FactorModelSection({
  id,
  title,
  model,
}: {
  id: "capm" | "ff3";
  title: string;
  model: FactorModelResult;
}) {
  return (
    <div className="qs-factor-model" data-testid={`factors-${id}`}>
      <div className="qs-factor-model__title">{title}</div>
      <FactorModelBody id={id} model={model} />
    </div>
  );
}

function FactorModelBody({ id, model }: { id: "capm" | "ff3"; model: FactorModelResult }) {
  if (model.status === "insufficient_observations") {
    return (
      <div className="qs-empty" data-testid={`${id}-insufficient`}>
        <div className="qs-empty__title">Not enough observations</div>
        <div className="qs-empty__msg">{observationsFraction(model.observations_used, model.required)}</div>
      </div>
    );
  }
  if (model.status === "undefined") {
    return (
      <div className="qs-empty" data-testid={`${id}-undefined`}>
        <div className="qs-empty__title">Regression undefined</div>
        <div className="qs-empty__msg">{model.reason}</div>
      </div>
    );
  }
  if (model.status === "unavailable") {
    return (
      <div className="qs-empty" data-testid={`${id}-unavailable`}>
        <div className="qs-empty__title">Unavailable</div>
        <div className="qs-empty__msg">{unavailableReasonLabel(model.reason)}</div>
      </div>
    );
  }
  if (!model.coefficients) return null;

  return (
    <>
      <div className="qs-analytics__meta" data-testid={`${id}-meta`}>
        {formatDate(model.aligned_start)} – {formatDate(model.aligned_end)} · {model.observations_used}{" "}
        observations · HAC lags {model.hac_lags}
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="qs-coef-table" data-testid={`${id}-coefficients`}>
          <thead>
            <tr>
              <th>Factor</th>
              <th>Estimate</th>
              <th>HAC SE</th>
              <th>t-stat</th>
              <th>p-value</th>
            </tr>
          </thead>
          <tbody>
            {model.coefficients.map((coef: RegressionCoefficient) => (
              <tr key={coef.name}>
                <th scope="row">{coefficientLabel(coef.name)}</th>
                <td>{formatCoefficientValue(coef.name, coef.estimate)}</td>
                <td>{coef.std_error == null ? "—" : formatCoefficientValue(coef.name, coef.std_error)}</td>
                <td>{formatRatio(coef.t_stat)}</td>
                <td>{formatPValue(coef.p_value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="qs-factor-model__stats">
        <span>R² {formatRatio(model.r_squared)}</span>
        <span>Adj. R² {formatRatio(model.adjusted_r_squared)}</span>
      </div>
    </>
  );
}
