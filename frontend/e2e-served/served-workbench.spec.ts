import { expect, test, type Page } from "@playwright/test";
import { access, mkdir, rm, rmdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";

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

test("serves the tracked React workbench from the default entry", async ({ page, request }) => {
  const health = await request.get("/api/health");
  expect(health.status()).toBe(200);
  expect(health.headers().server).toMatch(/^AgentWorkbench\//);
  const healthPayload = (await health.json()) as { workspace: string };
  const workspace = resolve(healthPayload.workspace);
  const sameTempRoot = process.platform === "win32"
    ? dirname(workspace).toLowerCase() === resolve(tmpdir()).toLowerCase()
    : dirname(workspace) === resolve(tmpdir());
  expect(sameTempRoot).toBe(true);
  expect(basename(workspace)).toMatch(/^agent-served-workspace-/);
  await writeFile(join(workspace, "README.md"), "# Cutover seed\n", "utf8");

  const [root, preview, legacy] = await Promise.all([
    request.get("/"),
    request.get("/preview/"),
    request.get("/legacy/"),
  ]);
  expect(root.status()).toBe(200);
  expect(preview.status()).toBe(200);
  expect(legacy.status()).toBe(200);
  expect(root.headers()["cache-control"]).toBe("no-store");
  expect(preview.headers()["cache-control"]).toBe("no-store");
  expect(legacy.headers()["cache-control"]).toBe("no-store");

  const rootBody = await root.body();
  const previewBody = await preview.body();
  const legacyBody = await legacy.body();
  expect(rootBody.equals(previewBody)).toBe(true);
  expect(rootBody.toString("utf8")).not.toContain("tokenicode-shell");
  expect(legacyBody.toString("utf8")).toContain("tokenicode-shell");

  const errors = collectBrowserErrors(page);
  await page.goto("/");
  await page.waitForLoadState("networkidle");

  await page.getByLabel("向 Agent 发送消息", { exact: true }).fill("cutover smoke");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByText(/FakeLLM received task: cutover smoke/)).toBeVisible();

  await page.getByRole("button", { name: "打开工作台", exact: true }).click();
  await expect(page.getByRole("heading", { name: "System overview", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Files", exact: true }).click();
  await page.getByRole("button", { name: "README.md", exact: true }).click();
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await page.getByRole("textbox", { name: "文件编辑器", exact: true }).fill("# Cutover seed\nupdated\n");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "确认保存", exact: true })).toBeVisible();

  const saveResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/file/save" && response.request().method() === "POST";
  });
  await page.getByRole("button", { name: "确认保存", exact: true }).click();
  const saveResponse = await saveResponsePromise;
  expect(saveResponse.status()).toBe(200);
  const savePayload = (await saveResponse.json()) as { run_id: string; snapshot_path: string };
  await expect(page.getByText("已保存", { exact: false })).toBeVisible();

  const runsRefresh = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/runs");
  await page.getByRole("button", { name: "刷新工作台", exact: true }).click();
  await runsRefresh;
  await page.getByRole("button", { name: "Runs", exact: true }).click();
  await page.getByRole("button", { name: savePayload.run_id, exact: true }).click();
  await page.getByRole("button", { name: "查看 diff", exact: true }).click();
  await expect(page.getByText("+updated", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "恢复", exact: true }).click();
  const restoreDialog = page.getByRole("dialog", { name: "确认恢复", exact: true });
  await expect(restoreDialog).toBeVisible();
  await expect(restoreDialog.getByText(savePayload.snapshot_path, { exact: false })).toBeVisible();
  await restoreDialog.getByRole("button", { name: "取消", exact: true }).click();

  expect(errors).toEqual([]);
});
