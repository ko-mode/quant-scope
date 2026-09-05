import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const usePriceHistory = vi.fn();
const useSecurityAnalytics = vi.fn();
const useComparison = vi.fn();
const useSecurityFactors = vi.fn();
const useSecuritySearch = vi.fn();
vi.mock("@/lib/api/hooks", () => ({
  usePriceHistory: (...args: unknown[]) => usePriceHistory(...args),
  useSecurityAnalytics: (...args: unknown[]) => useSecurityAnalytics(...args),
  useComparison: (...args: unknown[]) => useComparison(...args),
  useSecurityFactors: (...args: unknown[]) => useSecurityFactors(...args),
  useSecuritySearch: (...args: unknown[]) => useSecuritySearch(...args),
}));

import { SecurityTabs } from "./SecurityTabs";

function idleQuery() {
  return { data: undefined, isLoading: false, isError: false, isSuccess: false, refetch: vi.fn() };
}

beforeEach(() => {
  usePriceHistory.mockReset().mockReturnValue(idleQuery());
  useSecurityAnalytics.mockReset().mockReturnValue(idleQuery());
  useComparison.mockReset().mockReturnValue(idleQuery());
  useSecurityFactors.mockReset().mockReturnValue(idleQuery());
  useSecuritySearch.mockReset().mockReturnValue(idleQuery());
});

describe("SecurityTabs", () => {
  it("shows Price as the active tab by default", () => {
    render(<SecurityTabs ticker="NVDA" />);
    expect(screen.getByRole("tab", { name: "Price" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: "Risk & Return" }).getAttribute("aria-selected")).toBe(
      "false",
    );
    // Price content is mounted; Risk & Return's query is never invoked yet.
    expect(usePriceHistory).toHaveBeenCalled();
    expect(useSecurityAnalytics).not.toHaveBeenCalled();
  });

  it("switching to Risk & Return calls the analytics endpoint for the current ticker", () => {
    render(<SecurityTabs ticker="NVDA" />);
    fireEvent.click(screen.getByRole("tab", { name: "Risk & Return" }));
    expect(screen.getByRole("tab", { name: "Risk & Return" }).getAttribute("aria-selected")).toBe(
      "true",
    );
    expect(useSecurityAnalytics).toHaveBeenCalledWith("NVDA", "1Y");
  });

  it("switching to Factors calls the factors endpoint for the current ticker", () => {
    render(<SecurityTabs ticker="NVDA" />);
    fireEvent.click(screen.getByRole("tab", { name: "Factors" }));
    expect(screen.getByRole("tab", { name: "Factors" }).getAttribute("aria-selected")).toBe("true");
    expect(useSecurityFactors).toHaveBeenCalledWith("NVDA", "1Y");
  });

  it("switching back to Price re-shows price content", () => {
    render(<SecurityTabs ticker="NVDA" />);
    fireEvent.click(screen.getByRole("tab", { name: "Risk & Return" }));
    fireEvent.click(screen.getByRole("tab", { name: "Price" }));
    expect(screen.getByRole("tab", { name: "Price" }).getAttribute("aria-selected")).toBe("true");
  });

  it("Fundamentals is disabled and carries a SOON badge", () => {
    render(<SecurityTabs ticker="NVDA" />);
    const el = screen.getByText("Fundamentals").closest("[aria-disabled]");
    expect(el).toBeTruthy();
    expect(el?.tagName).not.toBe("BUTTON");
    expect(el?.querySelector(".qs-tab__soon")?.textContent).toBe("SOON");
  });

  it("Factors is enabled - no SOON badge, a real tab role", () => {
    render(<SecurityTabs ticker="NVDA" />);
    expect(screen.getByRole("tab", { name: "Factors" })).toBeTruthy();
    expect(screen.queryByText("Factors")?.closest("[aria-disabled]")).toBeNull();
  });

  it("switching to Comparison seeds the ticker set with the current page ticker", () => {
    render(<SecurityTabs ticker="NVDA" />);
    fireEvent.click(screen.getByRole("tab", { name: "Comparison" }));
    expect(screen.getByRole("tab", { name: "Comparison" }).getAttribute("aria-selected")).toBe("true");
    // Only 1 ticker selected -> useComparison must never be called with >=2 tickers
    // to fire; it is still invoked (React Query owns the `enabled` gate), so we
    // only assert the seeded set, not call-count.
    expect(useComparison).toHaveBeenCalledWith(["NVDA"], "1Y");
    expect(screen.getByTestId("comparison-empty-state")).toBeTruthy();
  });

  it("clicking a SOON tab does nothing (no tab role, stays on the current tab)", () => {
    render(<SecurityTabs ticker="NVDA" />);
    fireEvent.click(screen.getByText("Fundamentals"));
    expect(screen.getByRole("tab", { name: "Price" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByRole("tab", { name: "Fundamentals" })).toBeNull();
  });
});
