import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SecurityRead } from "@/lib/api/types";
import { SecurityHeader } from "./SecurityHeader";

const sec = (over: Partial<SecurityRead>): SecurityRead => ({
  ticker: "NVDA",
  name: "NVIDIA Corporation",
  exchange: "XNAS",
  currency: "USD",
  asset_type: "common_stock",
  is_active: true,
  first_trade_date: "1999-01-22",
  last_trade_date: null,
  delisted_date: null,
  ...over,
});

describe("SecurityHeader", () => {
  it("renders ticker, name, exchange code, mapped asset type, currency and status", () => {
    const { container } = render(<SecurityHeader security={sec({})} />);
    expect(screen.getByText("NVDA")).toBeTruthy();
    expect(screen.getByText("NVIDIA Corporation")).toBeTruthy();
    expect(screen.getByText("XNAS")).toBeTruthy();
    expect(screen.getByText("Common stock")).toBeTruthy();
    expect(screen.getByText("USD")).toBeTruthy();
    expect(screen.getByText("Active")).toBeTruthy();
    // internal id is never exposed
    expect(container.textContent).not.toMatch(/"id"|\bid:\b/);
  });

  it("shows a dash for a null asset type", () => {
    render(<SecurityHeader security={sec({ asset_type: null })} />);
    expect(screen.getByText("—")).toBeTruthy();
  });

  it("renders the inactive pill and a delisted alert with the date", () => {
    render(
      <SecurityHeader security={sec({ is_active: false, delisted_date: "2023-03-10" })} />,
    );
    expect(screen.getByTestId("security-status").textContent).toContain("INACTIVE");
    expect(screen.getByRole("note").textContent).toMatch(/inactive/i);
    expect(screen.getByRole("note").textContent).toContain("Mar 10, 2023");
  });
});
