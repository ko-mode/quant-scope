/**
 * TypeScript mirror of the Phase 1E read-only API response models
 * (`backend/src/quantscope/api/schemas.py`). Hand-written for three endpoints;
 * a generated client from the OpenAPI schema can replace this later.
 *
 * Price fields are JSON **numbers** (the Phase 1E contract), never strings.
 */

export type PriceSource = "tiingo" | "stooq";

export interface SecurityRead {
  ticker: string;
  name: string;
  exchange: string;
  currency: string;
  asset_type: string | null;
  is_active: boolean;
  first_trade_date: string | null;
  last_trade_date: string | null;
  delisted_date: string | null;
}

export interface SecurityListResponse {
  results: SecurityRead[];
  limit: number;
  offset: number;
  /** Rows in this page, not a universe-wide match total. */
  count: number;
}

export interface PriceBar {
  trade_date: string; // ISO date, YYYY-MM-DD
  open: number | null;
  high: number | null;
  low: number | null;
  close: number; // raw as-traded close
  adj_close: number; // vendor split+dividend adjusted (the V1 total-return series)
  volume: number | null;
  source: string;
}

export interface PriceHistoryResponse {
  ticker: string;
  /** The resolved source (defaulted from the backend price provider when omitted). */
  source: string;
  start: string | null;
  end: string | null;
  limit: number;
  offset: number;
  count: number;
  results: PriceBar[];
}

/**
 * TypeScript mirror of `backend/src/quantscope/api/analytics_schemas.py`
 * (Phase 2B / 2B.1). Every metric is a flat, discriminated object: value
 * fields are populated only when `status === "ok"`; otherwise they are
 * `null` and the suppression fields (`required` / `observations_used` /
 * `reason`) carry the explanation. Never coerce a non-`"ok"` metric's value
 * to `0` - render its `status` instead.
 */
export type MetricStatus = "ok" | "insufficient_observations" | "undefined" | "unavailable";

export interface MetricBase {
  status: MetricStatus;
  observations_used: number | null;
  required: number | null;
  reason: string | null;
}

export interface ReturnSummaryMetric extends MetricBase {
  mean_daily_return: number | null;
  stdev_daily_return: number | null;
  cumulative_return: number | null;
  min_daily_return: number | null;
  max_daily_return: number | null;
}

export interface VolatilityMetric extends MetricBase {
  daily_volatility: number | null;
  annualised_volatility: number | null;
  trading_days_per_year: number | null;
}

export interface SharpeMetric extends MetricBase {
  sharpe_ratio: number | null;
  mean_daily_excess_return: number | null;
  daily_excess_volatility: number | null;
  trading_days_per_year: number | null;
  risk_free_basis: string | null;
}

export interface DrawdownMetric extends MetricBase {
  max_drawdown: number | null;
  peak_date: string | null;
  trough_date: string | null;
  recovery_date: string | null;
  recovered: boolean | null;
}

export interface BetaMetric extends MetricBase {
  beta: number | null;
  alpha_daily: number | null;
  r_squared: number | null;
  aligned_start: string | null;
  aligned_end: string | null;
}

export interface VarEsMetric extends MetricBase {
  confidence: number | null;
  var: number | null;
  expected_shortfall: number | null;
  threshold_return: number | null;
  tail_observations: number | null;
  horizon_days: number | null;
  method: string | null;
}

/** One entry in `assumptions.suppressed` - why a metric is not `"ok"`. */
export interface SuppressedMetric {
  metric: string;
  status: MetricStatus;
  required: number | null;
  observations_used: number | null;
  reason: string | null;
}

/** ADR 0005 methodology block. Prefer these fields over hard-coded prose. */
export interface AnalyticsAssumptions {
  as_of: string | null;
  calendar: "XNYS";
  annualisation_factor: number;
  return_type: "total";
  adjustment_basis: "adjusted_close";
  data_source: string;
  missing_data_policy: string;
  rf_source: string;
  rf: number | null;
  rf_basis: string | null;
  benchmark: string;
  market_proxy: string;
  var_horizon_days: number;
  var_scaling: "none";
  confidence_levels: number[];
  min_observations: Record<string, number>;
  sharpe_annualisation_note: string;
  suppressed: SuppressedMetric[];
}

export interface AnalyticsResponse {
  ticker: string;
  source: string;
  adjustment_basis: "adjusted_close";
  requested_start: string | null;
  requested_end: string | null;
  price_observations: number;
  return_observations: number;
  analytics_start: string | null;
  analytics_end: string | null;
  return_summary: ReturnSummaryMetric;
  volatility: VolatilityMetric;
  sharpe: SharpeMetric;
  drawdown: DrawdownMetric;
  beta: BetaMetric;
  var_es_95: VarEsMetric;
  var_es_99: VarEsMetric;
  assumptions: AnalyticsAssumptions;
}

/**
 * TypeScript mirror of `backend/src/quantscope/api/comparison_schemas.py`
 * (Phase 3A `GET /compare`). Unlike `AnalyticsResponse` there is no nested
 * `assumptions` block - the handful of provenance fields that apply to a
 * comparison are flat top-level fields instead.
 */
export type ComparisonStatus = "ok" | "insufficient_observations" | "unavailable";

/**
 * Base-100 wealth index. `dates[0]` is always `null` (the pre-return anchor,
 * not a real market date); `dates.length === series[ticker].length ===
 * observations_used + 1` for every ticker. Never re-normalize this client
 * side - it is already the API's chosen convention.
 */
export interface NormalizedPerformance {
  base_value: number;
  dates: Array<string | null>;
  series: Record<string, number[]>;
}

/**
 * Pearson correlation of the one common aligned-return panel. `matrix[i][j]`
 * is `null` - never `0` - whenever either `tickers[i]` or `tickers[j]` has
 * zero return variance over the panel (see `zero_variance_tickers` on the
 * parent response), including a zero-variance ticker's own diagonal.
 */
export interface CorrelationMatrix {
  tickers: string[];
  matrix: Array<Array<number | null>>;
}

export interface ComparisonResponse {
  status: ComparisonStatus;
  tickers: string[];
  source: string;
  adjustment_basis: "adjusted_close";
  requested_start: string | null;
  requested_end: string | null;
  aligned_start: string | null;
  aligned_end: string | null;
  observations_used: number | null;
  required: number | null;
  reason: string | null;
  unavailable_tickers: string[] | null;
  zero_variance_tickers: string[] | null;
  normalized_performance: NormalizedPerformance | null;
  correlation: CorrelationMatrix | null;
}

/**
 * TypeScript mirror of `backend/src/quantscope/api/factors_schemas.py`
 * (Phase 3B `GET /securities/{ticker}/factors`). The SPY-based CAPM
 * regression and the Fama-French 3-factor regression are always returned
 * together in one response - never one model per request.
 *
 * `FactorModelStatus` preserves the same four-way distinction as
 * `MetricStatus`, applied independently to `capm` and `ff3`: `undefined`
 * means the aligned sample cleared its gate but the regression itself is not
 * estimable (a zero-variance regressor, or a rank-deficient design) - it is
 * never collapsed into `unavailable` (a missing *input*, before alignment).
 */
export type FactorModelStatus = "ok" | "insufficient_observations" | "undefined" | "unavailable";

/**
 * One OLS coefficient with Newey-West (HAC) inference. `estimate` is always
 * populated for an `ok` model; the four inference fields are independently
 * `null` - never `0`, never a raw `NaN`/`Infinity` - when that statistic is
 * undefined for this coefficient (e.g. a HAC standard error of exactly zero).
 */
export interface RegressionCoefficient {
  name: string;
  estimate: number;
  std_error: number | null;
  t_stat: number | null;
  p_value: number | null;
  ci_low: number | null;
  ci_high: number | null;
}

export interface FactorModelResult {
  status: FactorModelStatus;
  required: number | null;
  observations_used: number | null;
  reason: string | null;
  aligned_start: string | null;
  aligned_end: string | null;
  coefficients: RegressionCoefficient[] | null;
  r_squared: number | null;
  adjusted_r_squared: number | null;
  hac_lags: number | null;
}

/** ADR 0005 methodology block for the factors endpoint. `capm_vs_ff3_note`
 * is the mandatory disambiguation between the SPY CAPM beta (Risk & Return
 * tab) and the FF3 Mkt-RF coefficient below it - always render it verbatim. */
export interface FactorsAssumptions {
  capm_vs_ff3_note: string;
  alpha_note: string;
  adjustment_basis: "adjusted_close";
  factor_source: string;
  factor_frequency: "daily";
  rf_source: string;
  hac_lag_rule: string;
  min_observations: Record<string, number>;
}

export interface FactorsResponse {
  ticker: string;
  source: string;
  adjustment_basis: "adjusted_close";
  requested_start: string | null;
  requested_end: string | null;
  capm: FactorModelResult;
  ff3: FactorModelResult;
  assumptions: FactorsAssumptions;
}
