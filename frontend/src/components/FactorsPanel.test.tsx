import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FactorModelResult, FactorsResponse, RegressionCoefficient } from "@/lib/api/types";

const useSecurityFactors = vi.fn();
vi.mock("@/lib/api/hooks", () => ({
  useSecurityFactors: (...args: unknown[]) => useSecurityFactors(...args),
}));

import { FactorsPanel } from "./FactorsPanel";

function hookState(over: Record<string, unknown>) {
  useSecurityFactors.mockReturnValue({
    data: undefined,
    isLoading: false,
    isError: false,
    isSuccess: false,
    refetch: vi.fn(),
    ...over,
  });
}

function coef(overrides: Partial<RegressionCoefficient> = {}): RegressionCoefficient {
  return {
    name: "alpha",
    estimate: 0.0001,
    std_error: 0.00005,
    t_stat: 2.0,
    p_value: 0.04,
    ci_low: 0.00001,
    ci_high: 0.00019,
    ...overrides,
  };
}

function okModel(overrides: Partial<FactorModelResult> = {}): FactorModelResult {
  return {
    status: "ok",
    required: null,
    observations_used: 259,
    reason: null,
    aligned_start: "2022-01-04",
    aligned_end: "2022-12-30",
    coefficients: [coef(), coef({ name: "spy_excess", estimate: 1.2, t_stat: 12.0, p_value: 0.0 })],
    r_squared: 0.65,
    adjusted_r_squared: 0.64,
    hac_lags: 4,
    ...overrides,
  };
}

function factorsFixture(overrides: Partial<FactorsResponse> = {}): FactorsResponse {
  return {
    ticker: "NVDA",
    source: "tiingo",
    adjustment_basis: "adjusted_close",
    requested_start: null,
    requested_end: null,
    capm: okModel(),
    ff3: okModel({
      coefficients: [
        coef(),
        coef({ name: "mkt_rf", estimate: 1.1, t_stat: 10.0, p_value: 0.0 }),
        coef({ name: "smb", estimate: 0.4, t_stat: 3.0, p_value: 0.01 }),
        coef({ name: "hml", estimate: -0.3, t_stat: -2.5, p_value: 0.02 }),
      ],
    }),
    assumptions: {
      capm_vs_ff3_note:
        "The SPY CAPM beta and the FF3 Mkt-RF coefficient are different quantities. Both are labelled distinctly.",
      alpha_note: "Alpha is the daily regression intercept. It is not annualized.",
      adjustment_basis: "adjusted_close",
      factor_source: "kenneth_french",
      factor_frequency: "daily",
      rf_source: "kenneth_french_daily",
      hac_lag_rule: "floor(4 * (observations_used / 100) ** (2/9)), minimum 1",
      min_observations: { capm_regression: 126, ff3_regression: 250 },
    },
    ...overrides,
  };
}

beforeEach(() => useSecurityFactors.mockReset());

describe("FactorsPanel", () => {
  it("defaults to 1Y and requests that range for the current ticker", () => {
    hookState({ isSuccess: true, data: factorsFixture() });
    render(<FactorsPanel ticker="NVDA" />);
    expect(useSecurityFactors).toHaveBeenCalledWith("NVDA", "1Y");
    expect(screen.getByRole("button", { name: "1Y" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("switching range re-queries with the selected range", () => {
    hookState({ isSuccess: true, data: factorsFixture() });
    render(<FactorsPanel ticker="NVDA" />);
    fireEvent.click(screen.getByRole("button", { name: "3Y" }));
    expect(useSecurityFactors).toHaveBeenLastCalledWith("NVDA", "3Y");
  });

  it("renders CAPM coefficients with the SPY excess return label", () => {
    hookState({ isSuccess: true, data: factorsFixture() });
    render(<FactorsPanel ticker="NVDA" />);
    const capm = screen.getByTestId("capm-coefficients");
    expect(within(capm).getByText("Alpha")).toBeTruthy();
    expect(within(capm).getByText("SPY excess return")).toBeTruthy();
    expect(within(capm).getByText("1.200")).toBeTruthy(); // beta estimate, ratio formatting
  });

  it("renders FF3 coefficients with Mkt-RF/SMB/HML labels in order", () => {
    hookState({ isSuccess: true, data: factorsFixture() });
    render(<FactorsPanel ticker="NVDA" />);
    const ff3 = screen.getByTestId("ff3-coefficients");
    const headers = within(ff3).getAllByRole("rowheader").map((el) => el.textContent);
    expect(headers).toEqual(["Alpha", "Mkt-RF", "SMB", "HML"]);
  });

  it("renders HAC standard error, t-stat and p-value from the response, never recomputed", () => {
    hookState({ isSuccess: true, data: factorsFixture() });
    render(<FactorsPanel ticker="NVDA" />);
    const capm = screen.getByTestId("capm-coefficients");
    expect(within(capm).getByText("12.00")).toBeTruthy(); // spy_excess t-stat
    expect(within(capm).getByText("<0.0001")).toBeTruthy(); // spy_excess p-value (0.0)
  });

  it("renders a null inference field as an em dash, never as 0", () => {
    hookState({
      isSuccess: true,
      data: factorsFixture({
        capm: okModel({
          coefficients: [
            coef({ std_error: null, t_stat: null, p_value: null, ci_low: null, ci_high: null }),
            coef({ name: "spy_excess", estimate: 1.2 }),
          ],
        }),
      }),
    });
    render(<FactorsPanel ticker="NVDA" />);
    const capm = screen.getByTestId("capm-coefficients");
    const alphaRow = within(capm).getByText("Alpha").closest("tr");
    expect(alphaRow).toBeTruthy();
    expect(within(alphaRow as HTMLElement).getAllByText("—").length).toBeGreaterThan(0);
    expect(within(alphaRow as HTMLElement).queryByText("0.00")).toBeNull();
  });

  it("never renders an alpha_annualized value - alpha is always the daily intercept", () => {
    hookState({ isSuccess: true, data: factorsFixture() });
    render(<FactorsPanel ticker="NVDA" />);
    expect(screen.queryByText(/annualized alpha/i)).toBeNull();
    expect(screen.getByTestId("factors-methodology").textContent).toMatch(/not annualized/i);
  });

  it("CAPM insufficient_observations and FF3 ok render independently", () => {
    hookState({
      isSuccess: true,
      data: factorsFixture({
        capm: { ...okModel(), status: "insufficient_observations", observations_used: 80, required: 126, coefficients: null },
      }),
    });
    render(<FactorsPanel ticker="NVDA" />);
    expect(screen.getByTestId("capm-insufficient").textContent).toContain("80 / 126");
    expect(screen.getByTestId("ff3-coefficients")).toBeTruthy();
  });

  it("FF3 undefined (zero-variance regressor) renders the reason, CAPM stays ok", () => {
    hookState({
      isSuccess: true,
      data: factorsFixture({
        ff3: {
          status: "undefined",
          required: null,
          observations_used: 260,
          reason: "regressor 'smb' has zero variance",
          aligned_start: null,
          aligned_end: null,
          coefficients: null,
          r_squared: null,
          adjusted_r_squared: null,
          hac_lags: null,
        },
      }),
    });
    render(<FactorsPanel ticker="NVDA" />);
    expect(screen.getByTestId("ff3-undefined").textContent).toContain("regressor 'smb' has zero variance");
    expect(screen.getByTestId("capm-coefficients")).toBeTruthy();
  });

  it("unavailable renders a mapped reason label", () => {
    hookState({
      isSuccess: true,
      data: factorsFixture({
        capm: {
          status: "unavailable",
          required: null,
          observations_used: null,
          reason: "benchmark_security_not_found",
          aligned_start: null,
          aligned_end: null,
          coefficients: null,
          r_squared: null,
          adjusted_r_squared: null,
          hac_lags: null,
        },
      }),
    });
    render(<FactorsPanel ticker="NVDA" />);
    expect(screen.getByTestId("capm-unavailable").textContent).toContain("SPY benchmark unavailable");
  });

  it("renders the mandatory SPY-vs-Mkt-RF disambiguation note verbatim", () => {
    hookState({ isSuccess: true, data: factorsFixture() });
    render(<FactorsPanel ticker="NVDA" />);
    expect(screen.getByTestId("factors-methodology").textContent).toContain(
      factorsFixture().assumptions.capm_vs_ff3_note,
    );
  });

  it("shows a loading skeleton before data arrives", () => {
    hookState({ isLoading: true });
    render(<FactorsPanel ticker="NVDA" />);
    expect(screen.getByLabelText("Loading factor regressions")).toBeTruthy();
  });

  it("surfaces an error with a retry control that calls refetch", () => {
    const refetch = vi.fn();
    hookState({ isError: true, refetch });
    render(<FactorsPanel ticker="NVDA" />);
    expect(screen.getByRole("alert")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });
});
