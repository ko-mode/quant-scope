import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ComparisonResponse, NormalizedPerformance, SecurityRead } from "@/lib/api/types";

const useComparison = vi.fn();
vi.mock("@/lib/api/hooks", () => ({
  useComparison: (...args: unknown[]) => useComparison(...args),
}));

vi.mock("./ComparisonChart", () => ({
  ComparisonChart: ({ normalized }: { normalized: NormalizedPerformance }) => (
    <div data-testid="comparison-chart" data-tickers={Object.keys(normalized.series).join(",")} />
  ),
}));

let addCounter = 0;
vi.mock("./SecuritySearch", () => ({
  SecuritySearch: ({
    onSelect,
    excludeTickers,
  }: {
    onSelect?: (s: SecurityRead) => void;
    excludeTickers?: readonly string[];
  }) => (
    <button
      type="button"
      data-testid="add-ticker"
      data-exclude={(excludeTickers ?? []).join(",")}
      onClick={() => {
        addCounter += 1;
        onSelect?.({
          ticker: `T${addCounter}`,
          name: `Company ${addCounter}`,
          exchange: "XNAS",
          currency: "USD",
          asset_type: "common_stock",
          is_active: true,
          first_trade_date: null,
          last_trade_date: null,
          delisted_date: null,
        });
      }}
    >
      Add
    </button>
  ),
}));

import { ComparisonPanel } from "./ComparisonPanel";

function idleQuery(over: Record<string, unknown> = {}) {
  return { data: undefined, isLoading: false, isError: false, isSuccess: false, refetch: vi.fn(), ...over };
}

function comparisonFixture(overrides: Partial<ComparisonResponse> = {}): ComparisonResponse {
  return {
    status: "ok",
    tickers: ["NVDA", "T1"],
    source: "tiingo",
    adjustment_basis: "adjusted_close",
    requested_start: null,
    requested_end: null,
    aligned_start: "2024-01-02",
    aligned_end: "2024-12-30",
    observations_used: 2,
    required: null,
    reason: null,
    unavailable_tickers: null,
    zero_variance_tickers: null,
    normalized_performance: {
      base_value: 100,
      dates: [null, "2024-01-02", "2024-01-03"],
      series: { NVDA: [100, 105, 103], T1: [100, 101, 102] },
    },
    correlation: {
      tickers: ["NVDA", "T1"],
      matrix: [
        [1, 0.5],
        [0.5, 1],
      ],
    },
    ...overrides,
  };
}

beforeEach(() => {
  useComparison.mockReset().mockReturnValue(idleQuery());
  addCounter = 0;
});

describe("ComparisonPanel", () => {
  it("seeds the ticker set with the current page ticker and shows the empty state below 2 tickers", () => {
    render(<ComparisonPanel ticker="NVDA" />);
    expect(screen.getByRole("list", { name: "Selected securities" }).textContent).toContain("NVDA");
    expect(screen.getByTestId("comparison-empty-state")).toBeTruthy();
    expect(screen.getByText("Add at least one security to compare")).toBeTruthy();
    expect(useComparison).toHaveBeenLastCalledWith(["NVDA"], "1Y");
    // never attempts to render comparison content with only 1 ticker
    expect(screen.queryByTestId("comparison-chart")).toBeNull();
  });

  it("adding a security via the picker adds a chip and re-queries with both tickers", () => {
    render(<ComparisonPanel ticker="NVDA" />);
    fireEvent.click(screen.getByTestId("add-ticker"));
    expect(screen.getByRole("list", { name: "Selected securities" }).textContent).toContain("T1");
    expect(useComparison).toHaveBeenLastCalledWith(["NVDA", "T1"], "1Y");
    expect(screen.queryByTestId("comparison-empty-state")).toBeNull();
  });

  it("excludes already-selected tickers from the picker", () => {
    render(<ComparisonPanel ticker="NVDA" />);
    expect(screen.getByTestId("add-ticker").getAttribute("data-exclude")).toBe("NVDA");
  });

  it("removing a ticker back down to 1 shows the empty state again", () => {
    render(<ComparisonPanel ticker="NVDA" />);
    fireEvent.click(screen.getByTestId("add-ticker"));
    fireEvent.click(screen.getByRole("button", { name: "Remove T1" }));
    expect(screen.getByTestId("comparison-empty-state")).toBeTruthy();
    expect(useComparison).toHaveBeenLastCalledWith(["NVDA"], "1Y");
  });

  it("hides the add-security control once 8 tickers are selected", () => {
    render(<ComparisonPanel ticker="NVDA" />);
    for (let i = 0; i < 7; i++) fireEvent.click(screen.getByTestId("add-ticker"));
    expect(screen.getByRole("list", { name: "Selected securities" }).textContent).toContain("T7");
    expect(screen.queryByTestId("add-ticker")).toBeNull();
  });

  it("switching range re-queries with the selected range once 2+ tickers are selected", () => {
    render(<ComparisonPanel ticker="NVDA" />);
    fireEvent.click(screen.getByTestId("add-ticker"));
    fireEvent.click(screen.getByRole("button", { name: "3Y" }));
    expect(useComparison).toHaveBeenLastCalledWith(["NVDA", "T1"], "3Y");
  });

  it("renders the normalized-performance chart and correlation matrix for status ok", () => {
    useComparison.mockReturnValue(idleQuery({ isSuccess: true, data: comparisonFixture() }));
    render(<ComparisonPanel ticker="NVDA" />);
    fireEvent.click(screen.getByTestId("add-ticker"));

    expect(screen.getByTestId("comparison-chart").getAttribute("data-tickers")).toBe("NVDA,T1");
    const table = screen.getByTestId("correlation-matrix");
    expect(within(table).getAllByText("1.00")).toHaveLength(2);
    expect(within(table).getAllByText("0.50")).toHaveLength(2);
    expect(screen.getByTestId("comparison-meta").textContent).toContain("2 observations");
  });

  it("renders a null correlation cell as an em dash, never 0 or 1, with the zero-variance note", () => {
    useComparison.mockReturnValue(
      idleQuery({
        isSuccess: true,
        data: comparisonFixture({
          zero_variance_tickers: ["T1"],
          correlation: {
            tickers: ["NVDA", "T1"],
            matrix: [
              [1, null],
              [null, null],
            ],
          },
        }),
      }),
    );
    render(<ComparisonPanel ticker="NVDA" />);
    fireEvent.click(screen.getByTestId("add-ticker"));

    const table = screen.getByTestId("correlation-matrix");
    expect(within(table).getAllByText("—")).toHaveLength(3);
    expect(screen.getByText(/undefined for zero-variance ticker\(s\): t1/i)).toBeTruthy();
  });

  it("status unavailable names every offending ticker from the response", () => {
    useComparison.mockReturnValue(
      idleQuery({
        isSuccess: true,
        data: comparisonFixture({
          status: "unavailable",
          reason: "missing_price_history",
          unavailable_tickers: ["T1"],
          normalized_performance: null,
          correlation: null,
          aligned_start: null,
          aligned_end: null,
          observations_used: null,
        }),
      }),
    );
    render(<ComparisonPanel ticker="NVDA" />);
    fireEvent.click(screen.getByTestId("add-ticker"));
    expect(screen.getByTestId("comparison-unavailable").textContent).toContain("T1");
    expect(screen.queryByTestId("comparison-chart")).toBeNull();
  });

  it("status insufficient_observations shows the real observations_used / required counts", () => {
    useComparison.mockReturnValue(
      idleQuery({
        isSuccess: true,
        data: comparisonFixture({
          status: "insufficient_observations",
          observations_used: 12,
          required: 60,
          normalized_performance: null,
          correlation: null,
          aligned_start: null,
          aligned_end: null,
        }),
      }),
    );
    render(<ComparisonPanel ticker="NVDA" />);
    fireEvent.click(screen.getByTestId("add-ticker"));
    expect(screen.getByTestId("comparison-insufficient").textContent).toContain("12 / 60");
  });

  it("shows a loading skeleton before data arrives", () => {
    useComparison.mockReturnValue(idleQuery({ isLoading: true }));
    render(<ComparisonPanel ticker="NVDA" />);
    fireEvent.click(screen.getByTestId("add-ticker"));
    expect(screen.getByLabelText("Loading comparison")).toBeTruthy();
  });

  it("surfaces an error with a retry control that calls refetch", () => {
    const refetch = vi.fn();
    useComparison.mockReturnValue(idleQuery({ isError: true, refetch }));
    render(<ComparisonPanel ticker="NVDA" />);
    fireEvent.click(screen.getByTestId("add-ticker"));
    expect(screen.getByRole("alert")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });
});
