import { expect, test, type Page } from "@playwright/test";
import { access, mkdir, rm, rmdir, writeFile } from "node:fs/promises";
import { join } from "node:path";

async function fileExists(path: string) {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

async function waitForFile(path: string, timeoutMs = 5_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await fileExists(path)) return;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error(`Timed out waiting for served-workbench cleanup: ${path}`);
}

function collectBrowserErrors(page: Page) {
  const errors: string[] = [];
  page.on("requestfailed", (request) => {
    errors.push(`requestfailed ${request.url()}: ${request.failure()?.errorText || "unknown"}`);
  });
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.hostname === "127.0.0.1" && response.status() >= 400) {
      errors.push(`response ${response.status()} ${response.url()}`);
    }
  });
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console ${message.text()}`);
  });
  return errors;
}

test.afterAll(async () => {
  const controlDir = process.env.AGENT_SERVED_CONTROL_DIR;
  if (!controlDir) throw new Error("AGENT_SERVED_CONTROL_DIR is missing.");
  await mkdir(controlDir, { recursive: true });
  const stopFile = join(controlDir, "stop");
  const doneFile = join(controlDir, "done");
  await writeFile(stopFile, "stop\n", "utf8");
  await waitForFile(doneFile);
  await rm(stopFile, { force: true });
  await rm(doneFile, { force: true });
  await rmdir(controlDir);
});

test("serves the tracked React preview through AgentWorkbench", async ({ page, request }) => {
  const health = await request.get("/api/health");
  expect(health.status()).toBe(200);
  expect(health.headers().server).toMatch(/^AgentWorkbench\//);

  const errors = collectBrowserErrors(page);
  await page.goto("/preview/");
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("button", { name: "打开工作台", exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
