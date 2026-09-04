import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SecurityRead } from "@/lib/api/types";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const useSecuritySearch = vi.fn();
vi.mock("@/lib/api/hooks", () => ({ useSecuritySearch: () => useSecuritySearch() }));

import { SecuritySearch } from "./SecuritySearch";

const sec = (over: Partial<SecurityRead>): SecurityRead => ({
  ticker: "NVDA",
  name: "NVIDIA Corporation",
  exchange: "XNAS",
  currency: "USD",
  asset_type: "common_stock",
  is_active: true,
  first_trade_date: null,
  last_trade_date: null,
  delisted_date: null,
  ...over,
});

function state(over: Record<string, unknown>) {
  useSecuritySearch.mockReturnValue({
    data: undefined,
    isLoading: false,
    isError: false,
    isSuccess: false,
    refetch: vi.fn(),
    ...over,
  });
}

function openWith(query: string) {
  render(<SecuritySearch variant="hero" />);
  const input = screen.getByRole("combobox");
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: query } });
}

beforeEach(() => {
  push.mockReset();
  useSecuritySearch.mockReset();
});

describe("SecuritySearch", () => {
  it("renders results with ticker, name and exchange, linking to the ticker page", () => {
    state({
      isSuccess: true,
      data: {
        results: [sec({}), sec({ ticker: "NVDX", name: "Nano X", exchange: "XNYS" })],
        limit: 20,
        offset: 0,
        count: 2,
      },
    });
    openWith("nvda");

    expect(screen.getByText("NVIDIA Corporation")).toBeTruthy();
    expect(screen.getByText("XNAS")).toBeTruthy();
    expect(screen.getByText("XNYS")).toBeTruthy();
    const option = screen.getAllByRole("option")[0] as HTMLAnchorElement;
    expect(option.getAttribute("href")).toBe("/securities/NVDA");
  });

  it("marks an inactive security with an INACTIVE badge", () => {
    state({
      isSuccess: true,
      data: { results: [sec({ ticker: "SIVB", is_active: false })], limit: 20, offset: 0, count: 1 },
    });
    openWith("sivb");
    expect(screen.getByText("INACTIVE")).toBeTruthy();
  });

  it("shows the no-results message", () => {
    state({ isSuccess: true, data: { results: [], limit: 20, offset: 0, count: 0 } });
    openWith("zzzz");
    expect(screen.getByText(/no securities match/i)).toBeTruthy();
  });

  it("shows an error message with a retry control", () => {
    state({ isError: true, refetch: vi.fn() });
    openWith("nv");
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByRole("button", { name: /retry/i })).toBeTruthy();
  });

  it("navigates via the router on Enter over the active result", () => {
    state({
      isSuccess: true,
      data: { results: [sec({})], limit: 20, offset: 0, count: 1 },
    });
    openWith("nvda");
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(push).toHaveBeenCalledWith("/securities/NVDA");
  });

  it("with onSelect, clicking a result calls onSelect instead of navigating", () => {
    state({
      isSuccess: true,
      data: { results: [sec({})], limit: 20, offset: 0, count: 1 },
    });
    const onSelect = vi.fn();
    render(<SecuritySearch variant="bar" onSelect={onSelect} />);
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "nvda" } });
    fireEvent.click(screen.getByRole("option"));
    expect(onSelect).toHaveBeenCalledWith(sec({}));
    expect(push).not.toHaveBeenCalled();
  });

  it("with onSelect, Enter over the active result calls onSelect instead of navigating", () => {
    state({
      isSuccess: true,
      data: { results: [sec({})], limit: 20, offset: 0, count: 1 },
    });
    const onSelect = vi.fn();
    render(<SecuritySearch variant="bar" onSelect={onSelect} />);
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "nvda" } });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith(sec({}));
    expect(push).not.toHaveBeenCalled();
  });

  it("excludeTickers hides already-selected securities from the results", () => {
    state({
      isSuccess: true,
      data: {
        results: [sec({}), sec({ ticker: "MSFT", name: "Microsoft" })],
        limit: 20,
        offset: 0,
        count: 2,
      },
    });
    render(<SecuritySearch variant="bar" excludeTickers={["NVDA"]} />);
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "n" } });
    expect(screen.queryByText("NVIDIA Corporation")).toBeNull();
    expect(screen.getByText("Microsoft")).toBeTruthy();
  });

  it("a custom placeholder overrides the variant default", () => {
    state({ isSuccess: false, data: undefined });
    render(<SecuritySearch variant="bar" placeholder="Add security to compare" />);
    expect(screen.getByPlaceholderText("Add security to compare")).toBeTruthy();
  });
});
