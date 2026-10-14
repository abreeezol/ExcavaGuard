import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      // Vitest 不运行 React Server Components，测试中只替换服务端导入标记。
      "server-only": fileURLToPath(new URL("./tests/server-only.ts", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
    // Python bridge suites spawn subprocesses; serial files avoid sandbox
    // process contention and keep the test timeout above the 30s bridge budget.
    fileParallelism: false,
    testTimeout: 35_000,
    clearMocks: true,
    restoreMocks: true,
  },
});
