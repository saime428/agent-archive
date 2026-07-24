import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  reporter: "list",
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || "test-results",
  use: {
    baseURL: "http://127.0.0.1:4173/preview/",
    trace: process.env.PERF_EVIDENCE
      ? { mode: "on", screenshots: false, snapshots: false, sources: true }
      : process.env.PLAYWRIGHT_RECORD_EVIDENCE ? "on" : "retain-on-failure",
    video: process.env.PLAYWRIGHT_RECORD_EVIDENCE && !process.env.PERF_EVIDENCE ? "on" : "off",
  },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 4173",
    url: "http://127.0.0.1:4173/preview/",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
