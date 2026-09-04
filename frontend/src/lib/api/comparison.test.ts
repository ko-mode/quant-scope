import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./client";
import { getComparison, MAX_COMPARISON_TICKERS, MIN_COMPARISON_TICKERS } from "./comparison";

function mockJson(body: unknown, ok = true, status = 200) {
  return vi.fn(async () => ({
    ok,
    status,
    json: async () => body,
  })) as unknown as typeof fetch;
}

afterEach(() => vi.unstubAllGlobals());

describe("comparison API client", () => {
  it("joins tickers with a comma and forwards start / end / source", async () => {
    const fetchMock = mockJson({ status: "ok", tickers: ["AAPL", "MSFT"] });
    vi.stubGlobal("fetch", fetchMock);
    await getComparison(["AAPL", "MSFT"], { start: "2024-01-01", end: "2024-12-31", source: "stooq" });
    const url = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toContain("/compare?");
    expect(url).toContain("tickers=AAPL%2CMSFT");
    expect(url).toContain("start=2024-01-01");
    expect(url).toContain("end=2024-12-31");
    expect(url).toContain("source=stooq");
  });

  it("sends no query string beyond tickers for MAX (no start/end/source)", async () => {
    const fetchMock = mockJson({ status: "ok", tickers: ["AAPL", "MSFT"] });
    vi.stubGlobal("fetch", fetchMock);
    await getComparison(["AAPL", "MSFT"]);
    const url = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toBe("http://localhost:8000/compare?tickers=AAPL%2CMSFT");
  });

  it("raises ApiError carrying the FastAPI detail on a non-ok response", async () => {
    vi.stubGlobal("fetch", mockJson({ detail: "at least 2 distinct tickers are required" }, false, 422));
    await expect(getComparison(["AAPL"])).rejects.toMatchObject({ name: "ApiError", status: 422 });
    await expect(getComparison(["AAPL"])).rejects.toBeInstanceOf(ApiError);
  });

  it("exposes the same ticker-count bounds the router enforces", () => {
    expect(MIN_COMPARISON_TICKERS).toBe(2);
    expect(MAX_COMPARISON_TICKERS).toBe(8);
  });
});
