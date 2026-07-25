import { defineConfig } from "@playwright/test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = dirname(fileURLToPath(import.meta.url));
const repository = resolve(frontendRoot, "..");
const outputDir = resolve(process.env.PLAYWRIGHT_SERVED_OUTPUT_DIR || resolve(frontendRoot, "test-results/served"));
const controlDir = resolve(process.env.AGENT_SERVED_CONTROL_DIR || resolve(outputDir, "control"));

process.env.AGENT_SERVED_CONTROL_DIR = controlDir;

export default defineConfig({
  testDir: "./e2e-served",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: "list",
  outputDir,
  use: {
    baseURL: "http://127.0.0.1:4174",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "node frontend/scripts/start-served-workbench.mjs",
    cwd: repository,
    url: "http://127.0.0.1:4174/api/health",
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: "pipe",
    stderr: "pipe",
    env: { ...process.env, AGENT_SERVED_CONTROL_DIR: controlDir },
  },
});
