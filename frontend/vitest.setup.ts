import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// jsdom lacks ResizeObserver (used by PriceChart).
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (!("ResizeObserver" in globalThis)) {
  (globalThis as unknown as { ResizeObserver: typeof ResizeObserverStub }).ResizeObserver =
    ResizeObserverStub;
}

afterEach(() => cleanup());
