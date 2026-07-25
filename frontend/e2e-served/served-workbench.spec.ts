import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { access, mkdir, readFile, rm, rmdir, writeFile } from "node:fs/promises";
import { createServer, type IncomingMessage, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";

const FIXTURE_MARKERS = ["[served-approval]", "[served-command]", "[served-restart]", "[served-resume]"];
const REPOSITORY = resolve(process.cwd(), "..");
const PYTHON = resolve(
  process.env.AGENT_TEST_PYTHON
    || resolve(REPOSITORY, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python"),
);
let providerServer: Server;
let providerBaseUrl = "";
const providerCalls = new Map<string, number>();

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

async function waitFor(predicate: () => boolean | Promise<boolean>, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 50));
  }
  throw new Error("Timed out waiting for served-workbench condition.");
}

async function requestBody(request: IncomingMessage) {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(Buffer.from(chunk));
  return Buffer.concat(chunks).toString("utf8");
}

function fixtureAction(messages: unknown) {
  const transcript = JSON.stringify(messages);
  const marker = FIXTURE_MARKERS.reduce((latest, candidate) =>
    transcript.lastIndexOf(candidate) > transcript.lastIndexOf(latest) ? candidate : latest);
  const count = providerCalls.get(marker) || 0;
  providerCalls.set(marker, count + 1);
  if (marker === "[served-command]" && count === 0) {
    const child = "import os,time,pathlib; pathlib.Path('child.pid').write_text(str(os.getpid())); time.sleep(60)";
    const parent = [
      "import os,pathlib,subprocess,sys,time",
      "pathlib.Path('parent.pid').write_text(str(os.getpid()))",
      `subprocess.Popen([sys.executable, '-c', ${JSON.stringify(child)}])`,
      "time.sleep(60)",
    ].join("; ");
    return {
      message: "Run a cancellable process tree.",
      action: { name: "run_command", args: { argv: [PYTHON, "-c", parent], timeout_seconds: 120 } },
    };
  }
  if ((marker === "[served-approval]" || marker === "[served-restart]") && count === 0) {
    return {
      message: "Wait for approval without writing.",
      action: {
        name: "write_file",
        args: { path: `${marker.slice(1, -1)}-must-not-exist.txt`, content: "must not be written\n", create_parents: false },
      },
    };
  }
  return {
    message: "Fixture complete.",
    action: { name: "done", args: { final: `Fixture completed for ${marker}.`, changed_files: [], next_steps: [] } },
  };
}

async function startProviderFixture() {
  providerServer = createServer(async (request, response) => {
    try {
      const payload = JSON.parse(await requestBody(request)) as { messages?: unknown; stream?: boolean };
      const content = JSON.stringify(fixtureAction(payload.messages));
      if (payload.stream) {
        response.writeHead(200, { "Content-Type": "text/event-stream", Connection: "close" });
        response.end(`data: ${JSON.stringify({ choices: [{ delta: { content } }] })}\n\ndata: [DONE]\n\n`);
      } else {
        response.writeHead(200, { "Content-Type": "application/json", Connection: "close" });
        response.end(JSON.stringify({ choices: [{ message: { content } }] }));
      }
    } catch (error) {
      response.writeHead(500, { "Content-Type": "application/json", Connection: "close" });
      response.end(JSON.stringify({ error: String(error) }));
    }
  });
  await new Promise<void>((resolveListen, reject) => {
    providerServer.once("error", reject);
    providerServer.listen({ host: "127.0.0.1", port: 0 }, resolveListen);
  });
  const address = providerServer.address() as AddressInfo;
  providerBaseUrl = `http://127.0.0.1:${address.port}/v1`;
}

async function stopProviderFixture() {
  if (!providerServer?.listening) return;
  await new Promise<void>((resolveClose, reject) => providerServer.close((error) => error ? reject(error) : resolveClose()));
}

async function servedWorkspace(request: APIRequestContext) {
  const response = await request.get("/api/health");
  expect(response.status()).toBe(200);
  return resolve(((await response.json()) as { workspace: string }).workspace);
}

async function configureProvider(request: APIRequestContext) {
  const workspace = await servedWorkspace(request);
  await mkdir(join(workspace, ".agent"), { recursive: true });
  await writeFile(
    join(workspace, ".agent", "config.toml"),
    [
      'provider = "openai-compat"',
      'model = "served-fixture"',
      `base_url = ${JSON.stringify(providerBaseUrl)}`,
      "native_tools = false",
      'sandbox = "workspace-write"',
      'approval = "risky-confirm"',
      "",
    ].join("\n"),
    "utf8",
  );
  return workspace;
}

async function pidIsAlive(pid: number) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function collectBrowserErrors(page: Page) {
  const errors: string[] = [];
  page.on("requestfailed", (request) => {
    const failure = request.failure()?.errorText || "unknown";
    if (new URL(request.url()).pathname === "/api/chat/events" && failure.includes("ERR_ABORTED")) return;
    errors.push(`requestfailed ${request.url()}: ${failure}`);
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

test.beforeAll(startProviderFixture);

test.afterAll(async () => {
  try {
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
  } finally {
    await stopProviderFixture();
  }
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

test("cancels a pending approval without executing the write", async ({ page, request }) => {
  const workspace = await configureProvider(request);
  const blockedFile = join(workspace, "served-approval-must-not-exist.txt");
  const errors = collectBrowserErrors(page);
  await page.goto("/#/new");
  await page.getByLabel("向 Agent 发送消息", { exact: true }).fill("[served-approval] wait for cancellation");
  await page.getByRole("button", { name: "发送", exact: true }).click();

  await expect(page.getByRole("heading", { name: "批准前请核对真实影响", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "停止当前任务", exact: true }).click();

  await expect(page.getByText("error / cancelled", { exact: true })).toBeVisible({ timeout: 15_000 });
  expect(await fileExists(blockedFile)).toBe(false);
  expect(errors).toEqual([]);
});

test("stops a real Python parent and child process tree", async ({ page, request }) => {
  const workspace = await configureProvider(request);
  const parentPidFile = join(workspace, "parent.pid");
  const childPidFile = join(workspace, "child.pid");
  const errors = collectBrowserErrors(page);
  await page.goto("/#/new");
  await page.getByLabel("向 Agent 发送消息", { exact: true }).fill("[served-command] run a cancellable process tree");
  await page.getByRole("button", { name: "发送", exact: true }).click();

  await expect(page.getByRole("heading", { name: "批准前请核对真实影响", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "批准并继续", exact: true }).click();
  await waitForFile(parentPidFile, 10_000);
  await waitForFile(childPidFile, 10_000);
  const parentPid = Number((await readFile(parentPidFile, "utf8")).trim());
  const childPid = Number((await readFile(childPidFile, "utf8")).trim());
  expect(await pidIsAlive(parentPid)).toBe(true);
  expect(await pidIsAlive(childPid)).toBe(true);

  await page.getByRole("button", { name: "停止当前任务", exact: true }).click();

  await expect(page.getByText("error / cancelled", { exact: true })).toBeVisible({ timeout: 15_000 });
  await waitFor(async () => !(await pidIsAlive(parentPid)) && !(await pidIsAlive(childPid)), 10_000);
  expect(errors).toEqual([]);
});

test("recovers an interrupted job after service restart and resumes with a new message", async ({ page, request }) => {
  const workspace = await configureProvider(request);
  const blockedFile = join(workspace, "served-restart-must-not-exist.txt");
  const controlDir = process.env.AGENT_SERVED_CONTROL_DIR;
  if (!controlDir) throw new Error("AGENT_SERVED_CONTROL_DIR is missing.");
  const restartFile = join(controlDir, "restart");
  const restartedFile = join(controlDir, "restarted");
  await rm(restartedFile, { force: true });

  await page.goto("/#/new");
  await page.getByLabel("向 Agent 发送消息", { exact: true }).fill("[served-restart] remain pending across restart");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByRole("heading", { name: "批准前请核对真实影响", exact: true })).toBeVisible();

  await writeFile(restartFile, "restart\n", "utf8");
  await waitForFile(restartedFile, 10_000);
  await waitFor(async () => {
    try {
      return (await request.get("/api/health")).status() === 200;
    } catch {
      return false;
    }
  }, 20_000);

  await expect(page.getByText("error / interrupted", { exact: true })).toBeVisible({ timeout: 20_000 });
  expect(await fileExists(blockedFile)).toBe(false);

  await page.getByLabel("向 Agent 发送消息", { exact: true }).fill("[served-resume] continue without replaying the old tool");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByText("Fixture completed for [served-resume].", { exact: true })).toBeVisible({ timeout: 15_000 });
  expect(await fileExists(blockedFile)).toBe(false);

  const sessionId = decodeURIComponent(new URL(page.url()).hash.split("/").at(-1) || "");
  const history = await request.get(`/api/chats/${encodeURIComponent(sessionId)}`);
  expect(history.status()).toBe(200);
  const turns = ((await history.json()) as { turns: Array<{ job_id: string | null; resumed_from_job_id: string | null }> }).turns;
  expect(turns).toHaveLength(2);
  expect(turns[0].job_id).toBeTruthy();
  expect(turns[1].resumed_from_job_id).toBe(turns[0].job_id);
});
