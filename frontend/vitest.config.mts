import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
    // jsdom cold-start + transform can exceed the 5s default on the first test
    // of a file, especially on a loaded CI box; the tests themselves are fast.
    testTimeout: 20_000,
    hookTimeout: 20_000,
  },
});
