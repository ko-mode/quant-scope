import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const usePriceHistory = vi.fn();
const useSecurityAnalytics = vi.fn();
vi.mock("@/lib/api/hooks", () => ({
  usePriceHistory: (...args: unknown[]) => usePriceHistory(...args),
  useSecurityAnalytics: (...args: unknown[]) => useSecurityAnalytics(...args),
}));

import { SecurityTabs } from "./SecurityTabs";

function idleQuery() {
  return { data: undefined, isLoading: false, isError: false, isSuccess: false, refetch: vi.fn() };
}

beforeEach(() => {
  usePriceHistory.mockReset().mockReturnValue(idleQuery());
  useSecurityAnalytics.mockReset().mockReturnValue(idleQuery());
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

  it("switching back to Price re-shows price content", () => {
    render(<SecurityTabs ticker="NVDA" />);
    fireEvent.click(screen.getByRole("tab", { name: "Risk & Return" }));
    fireEvent.click(screen.getByRole("tab", { name: "Price" }));
    expect(screen.getByRole("tab", { name: "Price" }).getAttribute("aria-selected")).toBe("true");
  });

  it("Factors, Comparison and Fundamentals are disabled and carry a SOON badge", () => {
    render(<SecurityTabs ticker="NVDA" />);
    for (const label of ["Factors", "Comparison", "Fundamentals"]) {
      const el = screen.getByText(label).closest("[aria-disabled]");
      expect(el).toBeTruthy();
      expect(el?.tagName).not.toBe("BUTTON");
      expect(el?.querySelector(".qs-tab__soon")?.textContent).toBe("SOON");
    }
  });

  it("clicking a SOON tab does nothing (no tab role, stays on the current tab)", () => {
    render(<SecurityTabs ticker="NVDA" />);
    fireEvent.click(screen.getByText("Factors"));
    expect(screen.getByRole("tab", { name: "Price" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByRole("tab", { name: "Factors" })).toBeNull();
  });
});
