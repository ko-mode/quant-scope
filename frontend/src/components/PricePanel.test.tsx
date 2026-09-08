import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PriceBar, PriceHistoryResponse } from "@/lib/api/types";

const usePriceHistory = vi.fn();
vi.mock("@/lib/api/hooks", () => ({
  usePriceHistory: (...args: unknown[]) => usePriceHistory(...args),
}));
vi.mock("./PriceChart", () => ({
  PriceChart: ({ bars, showRaw }: { bars: PriceBar[]; showRaw: boolean }) => (
    <div data-testid="chart" data-bars={bars.length} data-showraw={String(showRaw)} />
  ),
}));

import { PricePanel } from "./PricePanel";

const priceBar = (d: string): PriceBar => ({
  trade_date: d,
  open: null,
  high: null,
  low: null,
  close: 100,
  adj_close: 95,
  volume: null,
  source: "tiingo",
});

function result(over: Partial<PriceHistoryResponse> = {}): PriceHistoryResponse {
  return {
    ticker: "NVDA",
    source: "tiingo",
    start: null,
    end: null,
    limit: 20000,
    offset: 0,
    count: over.results?.length ?? 0,
    results: [],
    ...over,
  };
}

function hookState(over: Record<string, unknown>) {
  usePriceHistory.mockReturnValue({
    data: undefined,
    isLoading: false,
    isError: false,
    isSuccess: false,
    refetch: vi.fn(),
    ...over,
  });
}

beforeEach(() => usePriceHistory.mockReset());

describe("PricePanel", () => {
  it("defaults to 1Y and requests that range", () => {
    hookState({ isSuccess: true, data: result({ results: [priceBar("2024-01-02")] }) });
    render(<PricePanel ticker="NVDA" />);
    expect(usePriceHistory).toHaveBeenCalledWith("NVDA", "1Y");
    expect(screen.getByRole("button", { name: "1Y" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("switching range re-queries with the selected range", () => {
    hookState({ isSuccess: true, data: result({ results: [priceBar("2024-01-02")] }) });
    render(<PricePanel ticker="NVDA" />);
    fireEvent.click(screen.getByRole("button", { name: "3Y" }));
    expect(usePriceHistory).toHaveBeenLastCalledWith("NVDA", "3Y");
    expect(screen.getByRole("button", { name: "3Y" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("plots adj_close bars and shows the resolved source provenance", () => {
    hookState({
      isSuccess: true,
      data: result({ source: "stooq", results: [priceBar("2024-01-02"), priceBar("2024-01-03")] }),
    });
    render(<PricePanel ticker="NVDA" />);
    expect(screen.getByTestId("chart").getAttribute("data-bars")).toBe("2");
    expect(screen.getByTestId("price-source").textContent).toBe("Source: stooq · Adjusted close");
  });

  it("toggles the raw-close overlay", () => {
    hookState({ isSuccess: true, data: result({ results: [priceBar("2024-01-02")] }) });
    render(<PricePanel ticker="NVDA" />);
    expect(screen.getByTestId("chart").getAttribute("data-showraw")).toBe("false");
    fireEvent.click(screen.getByLabelText(/show raw close/i));
    expect(screen.getByTestId("chart").getAttribute("data-showraw")).toBe("true");
  });

  it("empty history in a narrow range points the user at MAX without claiming history exists", () => {
    hookState({ isSuccess: true, data: result({ results: [] }) });
    render(<PricePanel ticker="NVDA" />);
    expect(screen.getByText("No observations in this range")).toBeTruthy();
    expect(screen.getByText(/try max to check for earlier price history/i)).toBeTruthy();
    expect(screen.queryByText(/has price history/i)).toBeNull();
    expect(screen.queryByTestId("chart")).toBeNull();
  });

  it("empty history at MAX reports nothing ingested", () => {
    hookState({ isSuccess: true, data: result({ results: [] }) });
    render(<PricePanel ticker="NVDA" />);
    fireEvent.click(screen.getByRole("button", { name: "MAX" }));
    expect(screen.getByText("No price history available")).toBeTruthy();
  });

  it("surfaces an error with a retry control", () => {
    hookState({ isError: true, refetch: vi.fn() });
    render(<PricePanel ticker="NVDA" />);
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByRole("button", { name: /retry/i })).toBeTruthy();
  });

  it("shows an em dash, never a fabricated 'tiingo', before the source is known (QS-08)", () => {
    hookState({ isLoading: true });
    render(<PricePanel ticker="NVDA" />);
    expect(screen.getByTestId("price-source").textContent).toBe("Source: — · Adjusted close");
  });

  it("shows a visible Refreshing indicator while placeholder data is displayed (QS-07)", () => {
    hookState({
      isSuccess: true,
      isPlaceholderData: true,
      data: result({ results: [priceBar("2024-01-02")] }),
    });
    render(<PricePanel ticker="NVDA" />);
    expect(screen.getByTestId("price-refreshing").textContent).toContain("Refreshing");
  });

  it("does not show the Refreshing indicator for fresh (non-placeholder) data", () => {
    hookState({ isSuccess: true, data: result({ results: [priceBar("2024-01-02")] }) });
    render(<PricePanel ticker="NVDA" />);
    expect(screen.queryByTestId("price-refreshing")).toBeNull();
  });
});
