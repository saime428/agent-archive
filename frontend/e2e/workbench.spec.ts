import { expect, test, type Page } from "@playwright/test";

const SESSION_ID = "session_e2e";
const JOB_ID = "job_e2e";
let submittedMessage = "";
let persistedFinal: ReturnType<typeof finalEvent> | null = null;

async function installWorkbenchMocks(page: Page) {
  await page.addInitScript(() => {
    class MockEventSource extends EventTarget {
      static sources: MockEventSource[] = [];
      onopen: ((event: Event) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      closed = false;

      constructor(public url: string) {
        super();
        MockEventSource.sources.push(this);
        queueMicrotask(() => this.onopen?.(new Event("open")));
      }

      close() {
        this.closed = true;
      }

      emit(name: string, payload: object) {
        if (!this.closed) this.dispatchEvent(new MessageEvent(name, { data: JSON.stringify(payload) }));
      }
    }

    Object.defineProperty(window, "EventSource", { configurable: true, value: MockEventSource });
    Object.defineProperty(window, "__agentMockSources", { configurable: true, value: MockEventSource.sources });
  });

  await page.route("http://127.0.0.1:4173/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (payload: object, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });

    if (path === "/api/health") {
      await json(healthFixture());
      return;
    }
    if (path === "/api/config") {
      await json(configFixture());
      return;
    }
    if (path === "/api/tools") {
      await json({ tools: [{ name: "read_file", category: "filesystem", dry_run: "safe", description: "Read a file." }] });
      return;
    }
    if (path === "/api/runs") {
      await json({
        workspace: "F:\\projects\\spatial-demo",
        runs: [{
          run_id: "run_e2e",
          status: "completed",
          risk_level: "low",
          created_at: "2026-07-24T00:00:00Z",
          updated_at: "2026-07-24T00:01:00Z",
          run_dir: "F:\\projects\\spatial-demo\\.agent\\runs\\run_e2e",
          summary_path: "summary.md",
          tool_calls_path: "tool_calls.jsonl",
        }],
      });
      return;
    }
    if (path === "/api/chats") {
      await json({ workspace: "F:\\projects\\spatial-demo", chats: [] });
      return;
    }
    if (path === `/api/chats/${SESSION_ID}`) {
      const turns = persistedFinal ? [{
        user: submittedMessage,
        final: persistedFinal.final,
        status: persistedFinal.status,
        run_id: persistedFinal.run_id,
        terminal_reason: persistedFinal.terminal_reason,
        last_observation_summary: persistedFinal.last_observation_summary,
        thinking_text: persistedFinal.thinking_text,
        process: persistedFinal.process,
      }] : [];
      await json({ session_id: SESSION_ID, title: "E2E task", created_at: "", updated_at: "", turn_count: turns.length, turns });
      return;
    }
    if (path === "/api/chat/start" && request.method() === "POST") {
      const body = JSON.parse(request.postData() || "{}") as { message?: string };
      submittedMessage = body.message || "";
      await json({ status: "running", job_id: JOB_ID, session_id: SESSION_ID });
      return;
    }
    if (path === "/api/chat/approval" && request.method() === "POST") {
      const body = JSON.parse(request.postData() || "{}") as { approve?: boolean };
      await json({ status: "ok", job_id: JOB_ID, approved: Boolean(body.approve) });
      return;
    }
    await json({ error: `Unhandled mock endpoint: ${path}` }, 404);
  });
}

async function emit(page: Page, name: string, payload: object) {
  if (name === "final") persistedFinal = payload as ReturnType<typeof finalEvent>;
  await page.evaluate(
    ({ eventName, eventPayload }) => {
      const sources = (window as unknown as { __agentMockSources: Array<{ emit: (name: string, payload: object) => void }> }).__agentMockSources;
      sources.at(-1)?.emit(eventName, eventPayload);
    },
    { eventName: name, eventPayload: payload },
  );
}

function healthFixture() {
  return {
    status: "ok",
    app: "agent-workbench",
    workspace: "F:\\projects\\spatial-demo",
    provider: "fake",
    model: "fixture-v1",
    mode: "guided",
    deepseek_api_key_env: "DEEPSEEK_API_KEY",
    deepseek_api_key_present: false,
    base_url: "",
    api_key_env: null,
    api_key_present: true,
    api_key_required: false,
    native_tools: false,
    provider_notice: "FakeLLM ready.",
    settings_readiness: {
      mode: "read-only",
      status: "ready",
      provider: "fake",
      model: "fixture-v1",
      base_url: "",
      api_key_env: null,
      api_key_present: true,
      api_key_required: false,
      native_tools: false,
      loaded_files: [],
      warnings: [],
      checks: ["Settings are readable."],
    },
    workspace_risk: {
      mode: "read-only",
      risk_level: "low",
      summary: "No failed recent runs, uncommitted files, or snapshots detected.",
      signals: { uncommitted_files: 0, failed_runs: 0, snapshots: 0 },
      uncommitted_files: [],
      checks: ["No workspace risk action needed."],
    },
    memory_review: { mode: "read-only", pending: [], active: [] },
  };
}

function configFixture() {
  return {
    workspace: "F:\\projects\\spatial-demo",
    config: {
      provider: "fake",
      model: "fixture-v1",
      mode: "guided",
      sandbox: "workspace-write",
      approval: "risky-confirm",
      dry_run: false,
      web_search_enabled: false,
      computer_read_enabled: false,
      native_tools: false,
      default_skills: ["code-dev"],
      allowed_commands: [],
      base_url: "",
      deepseek_api_key_env: "DEEPSEEK_API_KEY",
      api_key_env: "OPENAI_API_KEY",
      enabled_hooks: [],
      blocking_hooks: [],
      memory_auto_write: false,
      memory_max_items: 5,
      max_consecutive_errors: 3,
    },
    diagnostics: {
      global_config_path: "C:\\Users\\demo\\.agent\\config.toml",
      project_config_path: "F:\\projects\\spatial-demo\\.agent\\config.toml",
      loaded_files: [],
      warnings: [],
    },
  };
}

function finalEvent(sequence: number, final = "E2E final result.") {
  return {
    event: "final",
    sequence,
    elapsed_ms: sequence * 10,
    session_id: SESSION_ID,
    title: "E2E task",
    turn_count: 1,
    run_id: "run_e2e",
    status: "ok",
    completed: true,
    display_status: "completed",
    terminal_reason: "done",
    final,
    last_action: "done",
    last_observation_summary: "Completed.",
    error_code: null,
    error_message: null,
    process: ["Fixture completed."],
    thinking_text: "Fixture trace.",
  };
}

test.beforeEach(async ({ page }) => {
  submittedMessage = "";
  persistedFinal = null;
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installWorkbenchMocks(page);
});

test("streams a real turn into a durable final state", async ({ page }) => {
  await page.goto("./#/new");
  await page.getByLabel("向 Agent 发送消息", { exact: true }).fill("Run the browser fixture");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`#\\/chat\\/${SESSION_ID}$`));

  await emit(page, "chat_started", { event: "chat_started", sequence: 0, elapsed_ms: 0, session_id: SESSION_ID });
  await emit(page, "model_stream_chunk", { event: "model_stream_chunk", sequence: 1, elapsed_ms: 10, kind: "thinking", text: "Inspecting fixture.", chunk_chars: 19 });
  await emit(page, "model_stream_chunk", { event: "model_stream_chunk", sequence: 2, elapsed_ms: 20, kind: "content", text: "Working from real events.", chunk_chars: 25 });
  await emit(page, "final", finalEvent(3));

  await expect(page.getByText("E2E final result.", { exact: true })).toBeVisible();
  await expect(page.locator("canvas.context-field")).toHaveAttribute("data-frame", "static");
});

test("keeps a finished background job out of the current route", async ({ page }) => {
  await page.goto("./#/new");
  await page.getByLabel("向 Agent 发送消息", { exact: true }).fill("Background fixture");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await page.getByRole("button", { name: "新建任务", exact: true }).click();
  await expect(page).toHaveURL(/#\/new$/);

  await emit(page, "final", finalEvent(1, "Background result."));

  await expect(page.getByRole("heading", { name: "New task", exact: true })).toBeVisible();
  await expect(page.getByText("Background result.", { exact: true })).toHaveCount(0);
});

for (const decision of [
  { button: "批准并继续", event: "approval_granted", final: "Approved fixture completed." },
  { button: "拒绝", event: "approval_denied", final: "Denied fixture recorded." },
] as const) {
  test(`handles the ${decision.event} path`, async ({ page }) => {
    await page.goto("./#/new");
    await page.getByLabel("向 Agent 发送消息", { exact: true }).fill("Approval fixture");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await emit(page, "approval_required", {
      event: "approval_required",
      sequence: 0,
      elapsed_ms: 30,
      run_id: "run_e2e",
      action_index: 1,
      action: "run_command",
      message: "Inspect the local workspace.",
      args: { argv: ["git", "status", "--short"] },
      reason: "This action starts a local process.",
    });

    await expect(page.getByRole("heading", { name: "批准前请核对真实影响", exact: true })).toBeVisible();
    await page.getByRole("button", { name: decision.button, exact: true }).click();
    await emit(page, decision.event, {
      event: decision.event,
      sequence: 1,
      elapsed_ms: 40,
      run_id: "run_e2e",
      action_index: 1,
      action: "run_command",
      message: "Inspect the local workspace.",
      args: { argv: ["git", "status", "--short"] },
    });
    await emit(page, "final", finalEvent(2, decision.final));
    await expect(page.getByText(decision.final, { exact: true })).toBeVisible();
  });
}

test.describe("workspace shell", () => {
  test("opens the workspace plane with three entries and returns focus on close", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("./#/new");

    const openButton = page.getByRole("button", { name: "打开工作台", exact: true });
    await expect(openButton).toBeVisible();
    await openButton.click();

    await expect(page.getByRole("button", { name: "System", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Files", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Runs", exact: true })).toBeVisible();
    // Default view is System Overview with real health-derived signals.
    await expect(page.getByRole("heading", { name: "System overview", exact: true })).toBeVisible();
    await expect(page.getByText("FakeLLM ready.", { exact: true })).toBeVisible();
    // No PHASE 02 placeholder text once the real entry exists.
    await expect(page.getByText("PHASE 02 / WORKSPACE")).toHaveCount(0);

    await page.keyboard.press("Escape");
    await expect(page.getByRole("button", { name: "System", exact: true })).toHaveCount(0);
    await expect(openButton).toBeFocused();
  });

  test("uses a full-height modal sheet on mobile", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("./#/new");

    await page.getByRole("button", { name: "打开工作台", exact: true }).click();
    const sheet = page.getByRole("dialog", { name: "工作台", exact: true });
    await expect(sheet).toBeVisible();
    await expect(page.getByRole("button", { name: "System", exact: true })).toBeVisible();

    await page.getByRole("button", { name: "关闭工作台", exact: true }).click();
    await expect(sheet).toHaveCount(0);
  });
});

const visualVariants = [
  { name: "b-dark-desktop", width: 1440, height: 900, theme: "b", mode: "dark" },
  { name: "b-light-desktop", width: 1440, height: 900, theme: "b", mode: "light" },
  { name: "b-dark-mobile-390", width: 390, height: 844, theme: "b", mode: "dark" },
  { name: "b-dark-mobile-320", width: 320, height: 568, theme: "b", mode: "dark" },
  { name: "a-dark-desktop", width: 1440, height: 900, theme: "a", mode: "dark" },
  { name: "c-light-desktop", width: 1440, height: 900, theme: "c", mode: "light" },
] as const;

for (const variant of visualVariants) {
  test(`visual ${variant.name}`, async ({ page }) => {
    await page.setViewportSize({ width: variant.width, height: variant.height });
    await page.goto("./#/new");
    await page.getByLabel("主题", { exact: true }).selectOption(variant.theme);
    await page.getByLabel("显示模式", { exact: true }).selectOption(variant.mode);
    await expect(page).toHaveScreenshot(`${variant.name}.png`, { animations: "disabled" });

    const dimensions = await page.evaluate(() => ({ width: window.innerWidth, scrollWidth: document.body.scrollWidth }));
    expect(dimensions.scrollWidth).toBe(dimensions.width);
  });
}

test("keeps product chrome free of emoji while preserving payload containers", async ({ page }) => {
  await page.goto("./#/new");
  const chromeText = await page.locator("body").evaluate((body) => {
    const clone = body.cloneNode(true) as HTMLElement;
    clone.querySelectorAll("[data-payload]").forEach((element) => element.remove());
    return clone.textContent || "";
  });
  expect(chromeText).not.toMatch(/\p{Extended_Pictographic}|[✓✔✕✖⚠⚙⏎➜➝➞]/u);
});

test("keeps the desktop rail resize path keyboard accessible", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("./#/new");
  const separator = page.getByRole("separator", { name: "调整会话轨道宽度", exact: true });
  await expect(separator).toHaveAttribute("aria-valuenow", "326");
  await separator.press("ArrowRight");
  await expect(separator).toHaveAttribute("aria-valuenow", "342");
});

test("records the 30 second stream and canvas frame budget", async ({ page }, testInfo) => {
  test.skip(!process.env.PERF_EVIDENCE, "Only run for explicit performance evidence capture.");
  test.setTimeout(45_000);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("./#/new");
  await page.getByLabel("向 Agent 发送消息", { exact: true }).fill("Performance fixture");
  await page.getByRole("button", { name: "发送", exact: true }).click();

  const metrics = await page.evaluate(async () => {
    const sources = (window as unknown as { __agentMockSources: Array<{ emit: (name: string, payload: object) => void }> }).__agentMockSources;
    const source = sources.at(-1);
    const longTasks: number[] = [];
    const Observer = window.PerformanceObserver;
    const observer = Observer && Observer.supportedEntryTypes.includes("longtask")
      ? new Observer((list) => list.getEntries().forEach((entry) => longTasks.push(entry.duration)))
      : null;
    observer?.observe({ entryTypes: ["longtask"] });

    let sequence = 0;
    let frames = 0;
    const started = performance.now();
    const stream = window.setInterval(() => {
      source?.emit("model_stream_chunk", {
        event: "model_stream_chunk",
        sequence: sequence++,
        elapsed_ms: Math.round(performance.now() - started),
        kind: "content",
        text: "frame ",
        chunk_chars: 6,
      });
    }, 160);
    const pointer = window.setInterval(() => {
      const elapsed = performance.now() - started;
      dispatchEvent(new PointerEvent("pointermove", {
        clientX: 200 + Math.sin(elapsed / 500) * 140,
        clientY: 240 + Math.cos(elapsed / 700) * 120,
      }));
    }, 50);

    const result = await new Promise<{ fps: number; elapsed: number }>((resolve) => {
      const tick = (now: number) => {
        frames += 1;
        const elapsed = now - started;
        if (elapsed >= 30_000) resolve({ fps: frames / (elapsed / 1000), elapsed });
        else requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
    clearInterval(stream);
    clearInterval(pointer);
    observer?.disconnect();
    return {
      ...result,
      longTaskCount: longTasks.length,
      longestLongTask: longTasks.length ? Math.max(...longTasks) : 0,
      streamedChunks: sequence,
    };
  });

  await testInfo.attach("performance-metrics", {
    body: Buffer.from(JSON.stringify(metrics, null, 2)),
    contentType: "application/json",
  });
  console.info(`PERFORMANCE_METRICS ${JSON.stringify(metrics)}`);
  expect(metrics.fps).toBeGreaterThanOrEqual(55);
  expect(metrics.longestLongTask).toBeLessThan(200);
  await page.getByRole("button", { name: "关闭上下文画布", exact: true }).click();
  await expect(page.locator("canvas.context-field")).toHaveCount(0);
});
