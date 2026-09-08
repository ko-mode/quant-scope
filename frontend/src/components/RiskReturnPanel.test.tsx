import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AnalyticsResponse,
  BetaMetric,
  DrawdownMetric,
  MetricBase,
  MetricStatus,
  ReturnSummaryMetric,
  SharpeMetric,
  VarEsMetric,
  VolatilityMetric,
} from "@/lib/api/types";

const useSecurityAnalytics = vi.fn();
vi.mock("@/lib/api/hooks", () => ({
  useSecurityAnalytics: (...args: unknown[]) => useSecurityAnalytics(...args),
}));

import { RiskReturnPanel } from "./RiskReturnPanel";

function metric<T extends MetricBase>(status: MetricStatus, overrides: Partial<T> = {}): T {
  return {
    status,
    observations_used: null,
    required: null,
    reason: null,
    ...overrides,
  } as T;
}

function analyticsFixture(overrides: Partial<AnalyticsResponse> = {}): AnalyticsResponse {
  return {
    ticker: "NVDA",
    source: "tiingo",
    adjustment_basis: "adjusted_close",
    requested_start: null,
    requested_end: null,
    price_observations: 205,
    return_observations: 204,
    analytics_start: "2022-01-04",
    analytics_end: "2022-12-30",
    return_summary: metric<ReturnSummaryMetric>("ok", {
      observations_used: 204,
      mean_daily_return: 0.001,
      stdev_daily_return: 0.02,
      cumulative_return: 0.184,
      min_daily_return: -0.05,
      max_daily_return: 0.06,
    }),
    volatility: metric<VolatilityMetric>("ok", {
      observations_used: 204,
      daily_volatility: 0.02,
      annualised_volatility: 0.317,
      trading_days_per_year: 252,
    }),
    sharpe: metric<SharpeMetric>("ok", {
      observations_used: 204,
      sharpe_ratio: 1.42,
      mean_daily_excess_return: 0.0009,
      daily_excess_volatility: 0.02,
      trading_days_per_year: 252,
      risk_free_basis: "daily_series",
    }),
    drawdown: metric<DrawdownMetric>("ok", {
      observations_used: 204,
      max_drawdown: -0.221,
      peak_date: "2022-03-01",
      trough_date: "2022-06-01",
      recovery_date: "2022-09-01",
      recovered: true,
    }),
    beta: metric<BetaMetric>("ok", {
      observations_used: 204,
      beta: 1.73,
      alpha_daily: 0.0002,
      r_squared: 0.41,
      aligned_start: "2022-01-04",
      aligned_end: "2022-12-30",
    }),
    var_es_95: metric<VarEsMetric>("ok", {
      observations_used: 204,
      confidence: 0.95,
      var: 0.0416,
      expected_shortfall: 0.0625,
      threshold_return: -0.0416,
      tail_observations: 10,
      horizon_days: 1,
      method: "historical_lower_quantile",
    }),
    var_es_99: metric<VarEsMetric>("ok", {
      observations_used: 204,
      confidence: 0.99,
      var: 0.0788,
      expected_shortfall: 0.1013,
      threshold_return: -0.0788,
      tail_observations: 2,
      horizon_days: 1,
      method: "historical_lower_quantile",
    }),
    assumptions: {
      as_of: "2022-12-30",
      calendar: "XNYS",
      annualisation_factor: 252,
      return_type: "total",
      adjustment_basis: "adjusted_close",
      data_source: "tiingo",
      missing_data_policy: "one source, never merged",
      rf_source: "kenneth_french_daily",
      rf: null,
      rf_basis: "daily_series",
      benchmark: "SPY",
      market_proxy: "SPY",
      var_horizon_days: 1,
      var_scaling: "none",
      confidence_levels: [0.95, 0.99],
      min_observations: { return_summary: 60, volatility: 60, drawdown: 60, sharpe: 126, beta: 126, var_es: 126 },
      sharpe_annualisation_note: "sqrt(252) assumes i.i.d. daily returns.",
      suppressed: [],
    },
    ...overrides,
  } as AnalyticsResponse;
}

function hookState(over: Record<string, unknown>) {
  useSecurityAnalytics.mockReturnValue({
    data: undefined,
    isLoading: false,
    isError: false,
    isSuccess: false,
    refetch: vi.fn(),
    ...over,
  });
}

beforeEach(() => useSecurityAnalytics.mockReset());

describe("RiskReturnPanel", () => {
  it("defaults to 1Y and requests that range", () => {
    hookState({ isSuccess: true, data: analyticsFixture() });
    render(<RiskReturnPanel ticker="NVDA" />);
    expect(useSecurityAnalytics).toHaveBeenCalledWith("NVDA", "1Y");
    expect(screen.getByRole("button", { name: "1Y" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("switching range re-queries with the selected range", () => {
    hookState({ isSuccess: true, data: analyticsFixture() });
    render(<RiskReturnPanel ticker="NVDA" />);
    fireEvent.click(screen.getByRole("button", { name: "3Y" }));
    expect(useSecurityAnalytics).toHaveBeenLastCalledWith("NVDA", "3Y");
  });

  it("renders every ok metric with a formatted value and note, no fabricated CAGR cell", () => {
    hookState({ isSuccess: true, data: analyticsFixture() });
    render(<RiskReturnPanel ticker="NVDA" />);

    expect(within(screen.getByTestId("metric-cumulative_return")).getByText("18.40%")).toBeTruthy();
    expect(within(screen.getByTestId("metric-annualised_volatility")).getByText("31.70%")).toBeTruthy();
    expect(within(screen.getByTestId("metric-annualised_volatility")).getByText("Daily × √252")).toBeTruthy();
    expect(within(screen.getByTestId("metric-sharpe_ratio")).getByText("1.42")).toBeTruthy();
    expect(within(screen.getByTestId("metric-beta")).getByText("1.73")).toBeTruthy();
    expect(within(screen.getByTestId("metric-max_drawdown")).getByText("-22.10%")).toBeTruthy();
    expect(within(screen.getByTestId("metric-var_95")).getByText("4.16%")).toBeTruthy();
    expect(within(screen.getByTestId("metric-es_95")).getByText("6.25%")).toBeTruthy();
    expect(within(screen.getByTestId("metric-var_99")).getByText("7.88%")).toBeTruthy();
    expect(within(screen.getByTestId("metric-es_99")).getByText("10.13%")).toBeTruthy();

    // the mockup's placeholder "Annualized return" (CAGR) cell must not exist
    expect(screen.queryByText("Annualized return")).toBeNull();
    expect(screen.queryByText(/CAGR/i)).toBeNull();
  });

  it("preserves the backend's positive-loss VaR sign - no arbitrary flip", () => {
    hookState({ isSuccess: true, data: analyticsFixture() });
    render(<RiskReturnPanel ticker="NVDA" />);
    // var: 0.0416 (a positive loss magnitude per ADR 0017) renders as a
    // positive percentage, never negated to "-4.16%".
    expect(within(screen.getByTestId("metric-var_95")).getByText("4.16%")).toBeTruthy();
    expect(within(screen.getByTestId("metric-var_95")).queryByText("-4.16%")).toBeNull();
  });

  it("insufficient_observations renders the count from response fields, not hardcoded", () => {
    hookState({
      isSuccess: true,
      data: analyticsFixture({
        sharpe: metric<SharpeMetric>("insufficient_observations", { observations_used: 52, required: 126 }),
      }),
    });
    render(<RiskReturnPanel ticker="NVDA" />);
    const cell = screen.getByTestId("metric-sharpe_ratio");
    expect(within(cell).getByText("Insufficient data")).toBeTruthy();
    expect(within(cell).getByText("52 / 126 observations")).toBeTruthy();
    // never coerced to a number
    expect(within(cell).queryByText("0")).toBeNull();
    expect(within(cell).queryByText("0.00")).toBeNull();
  });

  it("undefined renders the API's reason verbatim", () => {
    hookState({
      isSuccess: true,
      data: analyticsFixture({
        sharpe: metric<SharpeMetric>("undefined", {
          observations_used: 200,
          reason: "zero excess-return variance",
        }),
      }),
    });
    render(<RiskReturnPanel ticker="NVDA" />);
    const cell = screen.getByTestId("metric-sharpe_ratio");
    expect(within(cell).getByText("Undefined")).toBeTruthy();
    expect(within(cell).getByText("zero excess-return variance")).toBeTruthy();
  });

  it.each([
    ["risk_free_series_not_ingested", "RF not ingested"],
    ["benchmark_security_not_found", "SPY benchmark unavailable"],
    ["benchmark_price_history_unavailable", "Benchmark history unavailable"],
    ["some_future_reason_code", "some future reason code"],
  ])("unavailable (%s) renders a mapped short label", (reason, expected) => {
    hookState({
      isSuccess: true,
      data: analyticsFixture({ beta: metric<BetaMetric>("unavailable", { reason }) }),
    });
    render(<RiskReturnPanel ticker="NVDA" />);
    const cell = screen.getByTestId("metric-beta");
    expect(within(cell).getByText("Unavailable")).toBeTruthy();
    expect(within(cell).getByText(expected)).toBeTruthy();
  });

  it("never renders a null metric value as zero", () => {
    hookState({
      isSuccess: true,
      data: analyticsFixture({ beta: metric<BetaMetric>("unavailable", { reason: "risk_free_series_not_ingested" }) }),
    });
    render(<RiskReturnPanel ticker="NVDA" />);
    const cell = screen.getByTestId("metric-beta");
    expect(within(cell).queryByText("0.00")).toBeNull();
    expect(within(cell).queryByText("0")).toBeNull();
  });

  it("renders source and adjusted-close provenance", () => {
    hookState({ isSuccess: true, data: analyticsFixture({ source: "stooq" }) });
    render(<RiskReturnPanel ticker="NVDA" />);
    expect(screen.getByTestId("analytics-source").textContent).toBe("Source: stooq · Adjusted close");
  });

  it("renders the observation-window metadata from real response fields", () => {
    hookState({ isSuccess: true, data: analyticsFixture() });
    render(<RiskReturnPanel ticker="NVDA" />);
    const meta = screen.getByTestId("analytics-meta").textContent ?? "";
    expect(meta).toContain("204 observations");
    expect(meta).toContain("2022");
  });

  it("methodology reflects real assumptions and never claims weekly analytics or rf=0%", () => {
    hookState({ isSuccess: true, data: analyticsFixture() });
    render(<RiskReturnPanel ticker="NVDA" />);
    const text = screen.getByTestId("methodology").textContent ?? "";
    expect(text).toMatch(/Kenneth French daily RF/);
    expect(text).toMatch(/SPY/);
    expect(text).toMatch(/1-day historical/);
    expect(text).toMatch(/×252/);
    expect(text.toLowerCase()).not.toMatch(/weekly/);
    expect(text).not.toMatch(/√52/);
    expect(text.toLowerCase()).not.toMatch(/sqrt\(52\)/);
    expect(text.toLowerCase()).not.toMatch(/rf\s*=\s*0%/);
    expect(text.toLowerCase()).not.toMatch(/ols,\s*weekly/);
  });

  it("methodology states RF is not ingested when rf_basis is null", () => {
    hookState({
      isSuccess: true,
      data: analyticsFixture({
        sharpe: metric<SharpeMetric>("unavailable", { reason: "risk_free_series_not_ingested" }),
        beta: metric<BetaMetric>("unavailable", { reason: "risk_free_series_not_ingested" }),
        assumptions: {
          ...analyticsFixture().assumptions,
          rf_source: "not_ingested",
          rf_basis: null,
        },
      }),
    });
    render(<RiskReturnPanel ticker="NVDA" />);
    expect(screen.getByTestId("methodology").textContent).toMatch(/risk-free series not ingested/);
  });

  it("shows a loading skeleton before data arrives", () => {
    hookState({ isLoading: true });
    render(<RiskReturnPanel ticker="NVDA" />);
    expect(screen.getByLabelText("Loading risk and return analytics")).toBeTruthy();
  });

  it("surfaces an error with a retry control that calls refetch", () => {
    const refetch = vi.fn();
    hookState({ isError: true, refetch });
    render(<RiskReturnPanel ticker="NVDA" />);
    expect(screen.getByRole("alert")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });

  it("shows a visible Refreshing indicator while placeholder data is displayed (QS-07)", () => {
    hookState({ isSuccess: true, isPlaceholderData: true, data: analyticsFixture() });
    render(<RiskReturnPanel ticker="NVDA" />);
    expect(screen.getByTestId("analytics-refreshing").textContent).toContain("Refreshing");
  });

  it("does not show the Refreshing indicator for fresh (non-placeholder) data", () => {
    hookState({ isSuccess: true, data: analyticsFixture() });
    render(<RiskReturnPanel ticker="NVDA" />);
    expect(screen.queryByTestId("analytics-refreshing")).toBeNull();
  });
});
