import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./client";
import { getSecurity, getSecurityAnalytics, getSecurityPrices, searchSecurities } from "./securities";

function mockJson(body: unknown, ok = true, status = 200) {
  return vi.fn(async () => ({
    ok,
    status,
    json: async () => body,
  })) as unknown as typeof fetch;
}

afterEach(() => vi.unstubAllGlobals());

describe("securities API client", () => {
  it("searchSecurities hits /securities with q + limit and returns typed rows", async () => {
    const fetchMock = mockJson({
      results: [
        {
          ticker: "NVDA",
          name: "NVIDIA Corporation",
          exchange: "XNAS",
          currency: "USD",
          asset_type: "common_stock",
          is_active: true,
          first_trade_date: null,
          last_trade_date: null,
          delisted_date: null,
        },
      ],
      limit: 20,
      offset: 0,
      count: 1,
    });
    vi.stubGlobal("fetch", fetchMock);

    const res = await searchSecurities("nvda");
    const url = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toMatch(/\/securities\?/);
    expect(url).toContain("q=nvda");
    expect(url).toContain("limit=20");
    expect(res.results[0].ticker).toBe("NVDA");
  });

  it("getSecurity encodes the ticker in the path", async () => {
    const fetchMock = mockJson({ ticker: "BRK.B" });
    vi.stubGlobal("fetch", fetchMock);
    await getSecurity("brk.b");
    const url = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toBe("http://localhost:8000/securities/brk.b");
  });

  it("getSecurityPrices forwards start / end / source / limit", async () => {
    const fetchMock = mockJson({ ticker: "NVDA", source: "tiingo", results: [] });
    vi.stubGlobal("fetch", fetchMock);
    await getSecurityPrices("NVDA", { start: "2024-01-01", end: "2024-12-31", source: "stooq" });
    const url = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toContain("/securities/NVDA/prices?");
    expect(url).toContain("start=2024-01-01");
    expect(url).toContain("end=2024-12-31");
    expect(url).toContain("source=stooq");
    expect(url).toContain("limit=20000");
  });

  it("getSecurityAnalytics forwards start / end / source for a bounded range", async () => {
    const fetchMock = mockJson({ ticker: "NVDA", source: "tiingo" });
    vi.stubGlobal("fetch", fetchMock);
    await getSecurityAnalytics("NVDA", { start: "2024-01-01", end: "2024-12-31", source: "stooq" });
    const url = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toContain("/securities/NVDA/analytics?");
    expect(url).toContain("start=2024-01-01");
    expect(url).toContain("end=2024-12-31");
    expect(url).toContain("source=stooq");
  });

  it("getSecurityAnalytics sends no query string for MAX (no start/end)", async () => {
    const fetchMock = mockJson({ ticker: "NVDA", source: "tiingo" });
    vi.stubGlobal("fetch", fetchMock);
    await getSecurityAnalytics("NVDA", {});
    const url = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toBe("http://localhost:8000/securities/NVDA/analytics");
  });

  it("getSecurityAnalytics URL-encodes the ticker like the other endpoints", async () => {
    const fetchMock = mockJson({ ticker: "BRK.B", source: "tiingo" });
    vi.stubGlobal("fetch", fetchMock);
    await getSecurityAnalytics("brk.b");
    const url = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toBe("http://localhost:8000/securities/brk.b/analytics");
  });

  it("raises ApiError carrying the FastAPI detail on a non-ok response", async () => {
    vi.stubGlobal("fetch", mockJson({ detail: "no security with ticker 'ZZZZ'" }, false, 404));
    await expect(getSecurity("ZZZZ")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
    });
    await expect(getSecurity("ZZZZ")).rejects.toBeInstanceOf(ApiError);
  });
});
