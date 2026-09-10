import { expect, test, type Page } from "@playwright/test";

const SESSION_ID = "session_e2e";
const JOB_ID = "job_e2e";
let submittedMessage = "";
let persistedFinal: ReturnType<typeof finalEvent> | null = null;
let cancelRequests = 0;
let resumeRequest: Record<string, unknown> | null = null;
let startRequests = 0;
let savedConfigUpdates: Record<string, unknown> | null = null;
let rejectConfigSave = false;
let savedFileRequests: Array<{ path?: string; content?: string }> = [];
let gitStatusMode: "normal" | "clean" | "nonrepo" | "error" | "diff-error" = "normal";
let gitDiffRequests: Array<{ path: string; area: string }> = [];
let terminalMode: "disabled" | "idle" | "error" = "disabled";
let terminalStatus: "idle" | "running" | "stopped" = "idle";
let terminalEvents: Array<{ sequence: number; stream: "stdout" | "stderr" | "system"; text: string }> = [];
let terminalStartRequest: Record<string, unknown> | null = null;
let terminalInputRequests: Array<Record<string, unknown>> = [];
let terminalStopRequests = 0;
let terminalReadySent = false;
let healthRequests = 0;
const LONG_FILE_NAME = "an-extremely-long-windows-file-name-that-must-not-break-the-layout-000000.md";

function terminalFixture(after = 0) {
  const active = terminalStatus !== "idle";
  return {
    enabled: terminalMode !== "disabled",
    terminal_id: active ? "terminal_mock" : null,
    status: terminalStatus,
    argv: active ? ["python", "-c", "print('ready')"] : [],
    cwd: active ? "." : "",
    timeout_seconds: active ? 30 : null,
    exit_code: terminalStatus === "stopped" ? 1 : null,
    events: terminalEvents.filter((event) => event.sequence >= after),
    next: terminalEvents.length,
    truncated: false,
    cleanup_error: null,
  };
}

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
      healthRequests += 1;
      await json(healthFixture());
      return;
    }
    if (path === "/api/config" && request.method() === "POST") {
      savedConfigUpdates = JSON.parse(request.postData() || "{}") as Record<string, unknown>;
      if (rejectConfigSave) {
        await json({ error: "mode must be step, guided, auto, or plan-first." }, 400);
        return;
      }
      const payload = configFixture();
      Object.assign(payload.config, savedConfigUpdates);
      await json({ ...payload, status: "ok" });
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
    if (path === "/api/git/status") {
      if (gitStatusMode === "error") {
        await json({ error: "Git status failed." }, 400);
      } else if (gitStatusMode === "nonrepo") {
        await json({
          git_available: true,
          is_repository: false,
          reason: "repository_root_outside_workspace",
          entries: [],
          entry_count: 0,
          truncated: false,
        });
      } else if (gitStatusMode === "clean") {
        await json({
          git_available: true,
          is_repository: true,
          reason: null,
          entries: [],
          entry_count: 0,
          truncated: false,
        });
      } else if (gitStatusMode === "diff-error") {
        await json({
          git_available: true,
          is_repository: true,
          reason: null,
          entries: [{
            path: "broken.txt",
            original_path: null,
            index_status: null,
            worktree_status: "M",
            staged: false,
            unstaged: true,
            untracked: false,
            conflicted: false,
          }],
          entry_count: 1,
          truncated: false,
        });
      } else {
        await json({
          git_available: true,
          is_repository: true,
          reason: null,
          entries: [
            {
              path: "src/app.py",
              original_path: null,
              index_status: "M",
              worktree_status: "M",
              staged: true,
              unstaged: true,
              untracked: false,
              conflicted: false,
            },
            {
              path: "rename new.txt",
              original_path: "rename old.txt",
              index_status: "R",
              worktree_status: null,
              staged: true,
              unstaged: false,
              untracked: false,
              conflicted: false,
            },
            {
              path: "notes ü space.txt",
              original_path: null,
              index_status: null,
              worktree_status: null,
              staged: false,
              unstaged: false,
              untracked: true,
              conflicted: false,
            },
            {
              path: "conflict.txt",
              original_path: null,
              index_status: "U",
              worktree_status: "U",
              staged: true,
              unstaged: true,
              untracked: false,
              conflicted: true,
            },
            {
              path: "empty.txt",
              original_path: null,
              index_status: "M",
              worktree_status: null,
              staged: true,
              unstaged: false,
              untracked: false,
              conflicted: false,
            },
          ],
          entry_count: 5,
          truncated: true,
        });
      }
      return;
    }
    if (path === "/api/git/diff") {
      const query = new URL(request.url()).searchParams;
      const requestedPath = query.get("path") || "";
      const area = query.get("area") || "";
      gitDiffRequests.push({ path: requestedPath, area });
      if (gitStatusMode === "diff-error") {
        await json({ error: "Git diff failed." }, 400);
        return;
      }
      const diff = requestedPath === "empty.txt"
        ? ""
        : `diff --git a/${requestedPath} b/${requestedPath}\n@@\n-${area === "staged" ? "base" : "staged"}\n+${area === "staged" ? "staged line" : "worktree line"}`;
      await json({ path: requestedPath, area, diff, truncated: area === "staged" && requestedPath === "src/app.py" });
      return;
    }
    if (path === "/api/terminal" && request.method() === "GET") {
      if (terminalMode === "error") {
        await json({ error: "Terminal status failed." }, 400);
        return;
      }
      const after = Number(new URL(request.url()).searchParams.get("after") || "0");
      if (terminalStatus === "running" && after > 0 && !terminalReadySent) {
        terminalReadySent = true;
        terminalEvents.push({ sequence: terminalEvents.length, stream: "stdout", text: "ready\n" });
      } else if (terminalStatus === "running" && after >= terminalEvents.length) {
        await new Promise((resolve) => setTimeout(resolve, 25));
      }
      await json(terminalFixture(after));
      return;
    }
    if (path === "/api/terminal/start") {
      terminalStartRequest = JSON.parse(request.postData() || "{}") as Record<string, unknown>;
      terminalStatus = "running";
      terminalEvents = [{ sequence: 0, stream: "system", text: "Process started.\n" }];
      await json(terminalFixture());
      return;
    }
    if (path === "/api/terminal/input") {
      const payload = JSON.parse(request.postData() || "{}") as Record<string, unknown>;
      terminalInputRequests.push(payload);
      terminalEvents.push({ sequence: terminalEvents.length, stream: "stdout", text: `${payload.data}\n` });
      await json(terminalFixture());
      return;
    }
    if (path === "/api/terminal/stop") {
      terminalStopRequests += 1;
      terminalStatus = "stopped";
      terminalEvents.push({ sequence: terminalEvents.length, stream: "system", text: "Process stopped.\n" });
      await json(terminalFixture());
      return;
    }
    if (path === "/api/runs") {
      await json({
        workspace: "F:\\projects\\spatial-demo",
        runs: [
          {
            run_id: "run_e2e",
            status: "completed",
            risk_level: "low",
            created_at: "2026-07-24T00:00:00Z",
            updated_at: "2026-07-24T00:01:00Z",
            run_dir: "F:\\projects\\spatial-demo\\.agent\\runs\\run_e2e",
            summary_path: "summary.md",
            tool_calls_path: "tool_calls.jsonl",
          },
          {
            // Real run ids are this long; short ids hid the index-column blowout.
            run_id: "run_20260725_045603_309947",
            status: "completed",
            risk_level: "low",
            created_at: "2026-07-25T04:56:03Z",
            updated_at: "2026-07-25T04:57:10Z",
            run_dir: "F:\\projects\\spatial-demo\\.agent\\runs\\run_20260725_045603_309947",
            summary_path: "summary.md",
            tool_calls_path: "tool_calls.jsonl",
          },
          {
            run_id: "run_attn",
            status: "failed",
            risk_level: "attention",
            created_at: "2026-07-24T00:02:00Z",
            updated_at: "2026-07-24T00:03:00Z",
            run_dir: "F:\\projects\\spatial-demo\\.agent\\runs\\run_attn",
            summary_path: "summary.md",
            tool_calls_path: "tool_calls.jsonl",
          },
        ],
      });
      return;
    }
    if (path === "/api/runs/run_e2e" || path === "/api/runs/run_20260725_045603_309947") {
      const detail = runDetailFixture();
      detail.run_id = path.split("/").pop() as string;
      await json(detail);
      return;
    }
    if (path === "/api/runs/run_attn") {
      const detail = runDetailFixture();
      detail.run_id = "run_attn";
      detail.summary = "Command failed while verifying the change.";
      detail.failure = {
        status: "failed",
        failure_count: 1,
        latest_failure: { action: "run_command", summary: "pytest exited with code 1." },
        next_checks: ["Read the failed observation summary.", "Inspect the trace around the failed action."],
      };
      detail.patch_review = {
        ...detail.patch_review,
        risk_level: "attention",
        summary: "Failed observations need review before patching.",
        next_action: "Resolve or explain the failed observation before patching.",
      };
      detail.recovery = { ...detail.recovery, status: "needs-attention" };
      await json(detail);
      return;
    }
    if (path === "/api/runs/run_missing") {
      await json({ error: "Run not found: run_missing" }, 404);
      return;
    }
    if (path === "/api/diff") {
      await json({
        path: "README.md",
        snapshot_path: "snap_readme_1",
        diff: "--- snapshot/README.md\n+++ current/README.md\n@@\n-old\n+new",
        truncated: false,
        current_exists: true,
        snapshot_missing: false,
      });
      return;
    }
    if (path === "/api/snapshot/restore" && request.method() === "POST") {
      const body = JSON.parse(request.postData() || "{}") as { path?: string; snapshot_path?: string };
      await json({ status: "ok", action: "restored", path: body.path, snapshot_path: body.snapshot_path });
      return;
    }
    if (path === "/api/search") {
      const query = new URL(request.url()).searchParams.get("query") || "";
      if (query === "empty") {
        await json({
          query,
          path: ".",
          matches: [],
          total_matches: 0,
          truncated: false,
          scan_truncated: false,
          scanned_files: 5,
          skipped_files: 0,
        });
      } else if (query === "broken") {
        await json({ error: "Workspace search failed." }, 400);
      } else {
        await json({
          query,
          path: ".",
          matches: [
            { path: "src/app.py", kind: "text", line: 2, excerpt: "    return 'needle'" },
            { path: "README.md", kind: "path", line: null, excerpt: null },
          ],
          total_matches: 52,
          truncated: true,
          scan_truncated: true,
          scanned_files: 10_000,
          skipped_files: 3,
        });
      }
      return;
    }
    if (path === "/api/files") {
      const requested = new URL(request.url()).searchParams.get("path");
      if (requested === "src") {
        await json({ path: "src", entries: [{ name: "app.py", path: "src/app.py", kind: "file", size: 120 }] });
      } else {
        await json({
          path: ".",
          entries: [
            { name: "src", path: "src", kind: "dir", size: null },
            { name: "README.md", path: "README.md", kind: "file", size: 64 },
            { name: "big.txt", path: "big.txt", kind: "file", size: 99999 },
            { name: "missing.txt", path: "missing.txt", kind: "file", size: 10 },
            {
              name: LONG_FILE_NAME,
              path: `F:\\projects\\spatial-demo\\deeply\\nested\\windows\\path\\${LONG_FILE_NAME}`,
              kind: "file",
              size: 42,
            },
          ],
        });
      }
      return;
    }
    if (path === "/api/file") {
      const requested = new URL(request.url()).searchParams.get("path");
      if (requested === "big.txt") {
        await json({ path: "big.txt", content: "截断内容预览。", truncated: true, size: 99999 });
      } else if (requested === "missing.txt") {
        await json({ error: "File not found: missing.txt" }, 400);
      } else {
        await json({ path: requested, content: "# Readme\nHello", truncated: false, size: 14 });
      }
      return;
    }
    if (path === "/api/file/save" && request.method() === "POST") {
      const body = JSON.parse(request.postData() || "{}") as { path?: string; content?: string };
      savedFileRequests.push(body);
      if (body.content === "reject save") {
        await json({ error: "Save rejected by fixture." }, 400);
        return;
      }
      await json({
        status: "ok",
        run_id: "run_save",
        path: body.path,
        bytes_written: (body.content || "").length,
        snapshot_path: "snap_readme_1",
        restore_hint: "agent restore snap_readme_1",
      });
      return;
    }
    if (path === "/api/chats") {
      // Realistic titles: real sessions are long prompts, which is what exposes
      // grid blowout and text overlap between the resource columns.
      await json({
        workspace: "F:\\projects\\spatial-demo",
        chats: [
          {
            session_id: "chat_long_1",
            title: "请务必调用 run_command 工具执行以下无写入命令，不能凭空回答，也不要改文件",
            turn_count: 3,
            created_at: "2026-07-24T00:00:00Z",
            updated_at: "2026-07-24T00:05:00Z",
            latest_user: "请务必调用 run_command 工具执行以下无写入命令",
            latest_final: "已完成。",
          },
          {
            session_id: "chat_long_2",
            title: "请只调用一次 run_command 工具执行以下无害命令，不要调用其他工具，不要改文件",
            turn_count: 1,
            created_at: "2026-07-23T00:00:00Z",
            updated_at: "2026-07-23T00:01:00Z",
            latest_user: "请只调用一次 run_command",
            latest_final: "已完成。",
          },
        ],
      });
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
        job_id: JOB_ID,
        resumed_from_job_id: null,
      }] : [];
      await json({ session_id: SESSION_ID, title: "E2E task", created_at: "", updated_at: "", turn_count: turns.length, turns });
      return;
    }
    if (path === "/api/chat/start" && request.method() === "POST") {
      startRequests += 1;
      const body = JSON.parse(request.postData() || "{}") as { message?: string };
      submittedMessage = body.message || "";
      await json({ status: "running", job_id: JOB_ID, session_id: SESSION_ID, run_id: "run_e2e" });
      return;
    }
    if (path === "/api/chat/cancel" && request.method() === "POST") {
      cancelRequests += 1;
      await json({ status: "cancel_requested", job_id: JOB_ID });
      return;
    }
    if (path === "/api/chat/resume" && request.method() === "POST") {
      resumeRequest = JSON.parse(request.postData() || "{}") as Record<string, unknown>;
      submittedMessage = String(resumeRequest.message || "");
      await json({ status: "running", job_id: "job_resume", session_id: SESSION_ID, run_id: "run_resume" });
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
  if (["final", "cancelled", "timed_out"].includes(name)) persistedFinal = payload as ReturnType<typeof finalEvent>;
  await expect.poll(() => page.evaluate(() => {
    const sources = (window as unknown as { __agentMockSources: Array<{ closed: boolean }> }).__agentMockSources;
    return sources.filter((source) => !source.closed).length;
  })).toBeGreaterThan(0);
  await page.evaluate(
    ({ eventName, eventPayload }) => {
      const sources = (window as unknown as { __agentMockSources: Array<{ closed: boolean; emit: (name: string, payload: object) => void }> }).__agentMockSources;
      sources.filter((source) => !source.closed).at(-1)?.emit(eventName, eventPayload);
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
    memory_review: {
      mode: "read-only",
      pending_count: 1,
      active_count: 1,
      candidates: [{
        candidate_id: "cand_1",
        source_run_id: "run_e2e",
        source_excerpt: "候选记忆：项目使用 pytest。",
        created_at: "2026-07-24T00:00:00Z",
        status: "pending",
      }],
      entries: [{
        entry_id: "mem_1",
        source_run_id: "run_e2e",
        source_excerpt: "生效记忆：前端在 frontend/ 目录。",
        created_at: "2026-07-24T00:00:00Z",
        status: "active",
        supersedes: null,
      }],
      checks: ["Review pending memory candidates"],
    },
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
      terminal_enabled: terminalMode !== "disabled",
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

function runDetailFixture() {
  return {
    run_id: "run_e2e",
    run_dir: "F:\\projects\\spatial-demo\\.agent\\runs\\run_e2e",
    // Real summaries are long multi-line reports with deep Windows paths.
    summary: [
      "- task: inspect project",
      "- action: done",
      "- status: ok",
      "",
      "## Project Instructions",
      "- project_instructions_path: F:\\projects\\spatial-demo\\AGENTS.md",
      "- project_instructions_loaded: false",
      "",
      "## Config",
      "- config_provider: deepseek",
      "- config_model: deepseek-v4-flash",
      "- config_sandbox: workspace-write",
    ].join("\n"),
    tool_calls: [{ line_number: 1, valid: true, raw: "{}", data: {}, error: null }],
    snapshots: [{ path: "README.md", snapshot_path: "snap_readme_1" }],
    review: {
      latest_action: "write_file",
      last_observation_summary: "Saved 20 bytes.",
      changed_files: ["README.md"],
      snapshot_count: 1,
      manual_checks: ["Open the changed files and review the saved summary."],
    },
    workflow: {
      mode: "read-only",
      verification_commands: ["python -m pytest tests/test_docs.py -q", "git diff --check"],
      review_steps: ["Open changed files from Task Review."],
    },
    failure: {
      status: "clear",
      failure_count: 0,
      latest_failure: null as Record<string, unknown> | null,
      next_checks: ["No failed observations recorded for this run."],
    },
    patch_review: {
      mode: "read-only",
      risk_level: "medium",
      summary: "1 changed file(s), 1 snapshot(s), no failed observations.",
      checks: ["Open changed files from Task Review."],
      verification_commands: ["git diff --check"],
      next_action: "Review changes and run suggested verification commands from a terminal.",
    },
    recovery: {
      mode: "read-only",
      status: "snapshot-review",
      rollback_available: true,
      summary: "1 snapshot(s) are available for manual review.",
      latest_failure: null,
      steps: ["Open Snapshots and use Show diff before any restore."],
      checks: ["Restore only after confirming the diff."],
      verification_commands: ["git diff --check"],
      next_action: "Review snapshots before making further file changes.",
    },
    replay: {
      mode: "read-only",
      step_count: 2,
      steps: [
        { line_number: 1, phase: "action", action: "write_file", status: "ok", summary: "Saved README.", terminal: false, policy_decision: "" },
        { line_number: 2, phase: "action", action: "done", status: "ok", summary: "Completed.", terminal: true, policy_decision: "" },
      ],
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

function cancelledEvent(sequence: number) {
  return {
    ...finalEvent(sequence, ""),
    event: "cancelled",
    status: "error",
    completed: false,
    display_status: "error",
    terminal_reason: "cancelled",
    last_action: "run_control",
    last_observation_summary: "Run cancelled.",
    error_code: "CANCELLED",
    error_message: "Run cancelled.",
  };
}

test.beforeEach(async ({ page }) => {
  submittedMessage = "";
  persistedFinal = null;
  cancelRequests = 0;
  resumeRequest = null;
  startRequests = 0;
  savedConfigUpdates = null;
  rejectConfigSave = false;
  savedFileRequests = [];
  gitStatusMode = "normal";
  gitDiffRequests = [];
  terminalMode = "disabled";
  terminalStatus = "idle";
  terminalEvents = [];
  terminalStartRequest = null;
  terminalInputRequests = [];
  terminalStopRequests = 0;
  terminalReadySent = false;
  healthRequests = 0;
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installWorkbenchMocks(page);
});

test("orb phase details follow SSE activity and support click and keyboard", async ({ page }) => {
  await page.goto("./#/new");
  await startTurn(page);
  const toggle = page.getByRole("button", { name: "阶段详情", exact: true });
  const details = page.getByRole("region", { name: "阶段详情", exact: true });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(details).toContainText("等待服务端事件");

  const action = { run_id: "run_orb", action_index: 1, action: "read_file", message: "Read", args: {} };
  await emit(page, "tool_start", { ...action, event: "tool_start", sequence: 0, elapsed_ms: 1 });
  await expect(details).toContainText("当前状态：tool / searching");
  await expect(details).toContainText("事件类型：tool_start");
  await expect(details).toContainText("最近活动：正在执行 read_file");
  await emit(page, "observation", { ...action, event: "observation", sequence: 1, elapsed_ms: 2, status: "ok", summary: "Latest file activity" });
  await expect(details).toContainText("事件类型：observation");
  await expect(details).toContainText("最近活动：Latest file activity");
  await expect(details).not.toContainText("正在执行 read_file");
  await emit(page, "capability_warning", { event: "capability_warning", sequence: 2, elapsed_ms: 3, run_id: "run_orb", requested: "native", fallback: "json" });
  await expect(details).toContainText("事件类型：observation");

  await emit(page, "model_stream_chunk", { event: "model_stream_chunk", sequence: 3, elapsed_ms: 4, kind: "thinking", text: "Latest reasoning", chunk_chars: 16 });
  await expect(details).toContainText("当前状态：stream / weaving");
  await expect(details).toContainText("事件类型：model_stream_chunk");
  await expect(details).toContainText("最近活动：Latest reasoning");
  await toggle.focus();
  await page.keyboard.press("Enter");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(details).toBeHidden();
  await page.keyboard.press("Space");
  await expect(details).toBeVisible();
  await emit(page, "final", finalEvent(4));
  await expect(toggle).toHaveCount(0);
  await expect(details).toHaveCount(0);
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
  await expect(page.locator("canvas.context-field")).toHaveCount(0);
});

test("keeps a finished background job out of the current route", async ({ page }) => {
  await page.goto("./#/new");
  await page.getByLabel("向 Agent 发送消息", { exact: true }).fill("Background fixture");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await page.getByRole("button", { name: "新建任务", exact: true }).click();
  await expect(page).toHaveURL(/#\/new$/);

  await emit(page, "final", finalEvent(1, "Background result."));

  await expect(page.getByRole("heading", { name: "新任务", exact: true })).toBeVisible();
  await expect(page.getByText("Background result.", { exact: true })).toHaveCount(0);
});

test("cancels once, persists the terminal turn, and resumes with a new message", async ({ page }) => {
  await page.goto("./#/new");
  await page.getByLabel("向 Agent 发送消息", { exact: true }).fill("Long fixture");
  await page.getByRole("button", { name: "发送", exact: true }).click();

  const stop = page.getByRole("button", { name: "停止当前任务", exact: true });
  await expect(stop).toBeVisible();
  await stop.click();
  await expect(page.getByRole("button", { name: "正在停止当前任务", exact: true })).toBeDisabled();
  expect(cancelRequests).toBe(1);

  await emit(page, "cancelled", cancelledEvent(0));
  await expect(page.getByText("error / cancelled", { exact: true })).toBeVisible();

  await page.getByLabel("向 Agent 发送消息", { exact: true }).fill("Continue without replaying tools");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  expect(resumeRequest).toEqual({ job_id: JOB_ID, message: "Continue without replaying tools" });

  await emit(page, "final", finalEvent(0, "Resumed fixture completed."));
  await expect(page.getByText("Resumed fixture completed.", { exact: true })).toBeVisible();
});

test("refreshes the same active job without creating a second turn", async ({ page }) => {
  await page.goto("./#/new");
  await page.getByLabel("向 Agent 发送消息", { exact: true }).fill("Refresh fixture");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`#\\/chat\\/${SESSION_ID}$`));
  await expect(page.getByRole("button", { name: "停止当前任务", exact: true })).toBeVisible();
  expect(startRequests).toBe(1);

  await page.reload();

  await expect(page).toHaveURL(new RegExp(`#\\/chat\\/${SESSION_ID}$`));
  await expect(page.getByRole("button", { name: "停止当前任务", exact: true })).toBeVisible();
  expect(startRequests).toBe(1);
  await emit(page, "chat_started", { event: "chat_started", sequence: 0, elapsed_ms: 0, session_id: SESSION_ID });
  await emit(page, "cancelled", cancelledEvent(1));
  await expect(page.getByText("error / cancelled", { exact: true })).toBeVisible();
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

test.describe("command palette and layout", () => {
  async function runCommand(page: Page, query: string) {
    await page.keyboard.press("Control+K");
    const search = page.getByLabel("搜索命令", { exact: true });
    await expect(search).toBeFocused();
    await search.fill(query);
    await page.keyboard.press("Enter");
  }

  test("filters with the keyboard, executes every workspace command, and preserves modal focus", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("./#/new");
    const trigger = page.getByRole("button", { name: "打开命令面板", exact: true });
    await expect(trigger).toBeVisible();

    await page.keyboard.press("Control+K");
    const palette = page.getByRole("dialog", { name: "命令面板", exact: true });
    await expect(palette).toBeVisible();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowUp");
    await page.keyboard.press("Escape");
    await expect(trigger).toBeFocused();

    for (const view of ["Files", "Git", "Terminal", "Runs", "System"]) {
      await runCommand(page, `打开 ${view}`);
      const tab = page.getByRole("button", { name: view, exact: true });
      await expect(tab).toHaveAttribute("aria-pressed", "true");
      await page.getByRole("button", { name: "关闭工作台", exact: true }).click();
      await expect(trigger).toBeFocused();
    }

    await page.getByRole("button", { name: "打开工作台", exact: true }).click();
    await page.keyboard.press("Control+K");
    await expect(palette).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(palette).toHaveCount(0);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect.poll(() => page.locator(".workspace-plane").evaluate((node) => node.matches(":modal"))).toBe(true);
    await page.keyboard.press("Control+K");
    await expect(palette).toHaveCount(0);
  });

  test("keeps an external dialog usable while the workspace crosses the modal breakpoint", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("./#/new");
    await page.getByRole("button", { name: "打开工作台", exact: true }).click();
    await page.keyboard.press("Control+K");

    const panel = page.locator(".workspace-plane");
    const search = page.getByLabel("搜索命令", { exact: true });
    await expect(search).toBeFocused();
    await page.setViewportSize({ width: 1000, height: 900 });
    await search.fill("打开 Git");
    await expect(search).toBeFocused();
    await expect.poll(() => panel.evaluate((node) => node.matches(":modal"))).toBe(false);

    await page.keyboard.press("Escape");
    await expect.poll(() => panel.evaluate((node) => node.matches(":modal"))).toBe(true);
    await page.setViewportSize({ width: 1440, height: 900 });
    await expect.poll(() => panel.evaluate((node) => node.matches(":modal"))).toBe(false);
    await page.keyboard.press("Control+K");
    await expect(search).toBeFocused();
  });

  test("preserves a session rename draft across the workspace modal breakpoint", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`./#/chat/${SESSION_ID}`);
    await page.getByRole("button", { name: "打开工作台", exact: true }).click();
    await page.getByRole("button", { name: "重命名会话", exact: true }).first().click();

    const panel = page.locator(".workspace-plane");
    const title = page.getByLabel("会话名称", { exact: true });
    await title.fill("保留的重命名草稿");
    await page.setViewportSize({ width: 1000, height: 900 });
    await expect(title).toHaveValue("保留的重命名草稿");
    await expect(title).toBeFocused();
    await expect.poll(() => panel.evaluate((node) => node.matches(":modal"))).toBe(false);

    await page.getByRole("button", { name: "取消", exact: true }).click();
    await expect.poll(() => panel.evaluate((node) => node.matches(":modal"))).toBe(true);
  });

  test("runs top-level commands and restores only bounded layout state after reload", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`./#/chat/${SESSION_ID}`);

    const resizer = page.getByRole("separator", { name: "调整会话轨道宽度", exact: true });
    await resizer.press("End");
    await runCommand(page, "收起会话轨道");
    await expect(page.getByRole("button", { name: "展开会话轨道", exact: true })).toBeVisible();
    await runCommand(page, "隐藏上下文画布");
    await expect(page.locator("canvas.context-field")).toHaveCount(0);

    const requestsBefore = healthRequests;
    await runCommand(page, "刷新状态");
    await expect.poll(() => healthRequests).toBeGreaterThan(requestsBefore);
    await runCommand(page, "打开 Git");
    await expect(page.getByRole("button", { name: "Git", exact: true })).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: "关闭工作台", exact: true }).click();
    await runCommand(page, "新建任务");
    await expect(page).toHaveURL(/#\/new$/);

    const stored = await page.evaluate(() => JSON.parse(localStorage.getItem("agent.frontend.layout") || "{}"));
    expect(stored).toEqual({ railOpen: false, railWidth: 420, canvasEnabled: false, workspaceView: "git" });

    await page.reload();
    await expect(page.getByRole("button", { name: "展开会话轨道", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "展开会话轨道", exact: true }).click();
    await expect(page.getByRole("separator", { name: "调整会话轨道宽度", exact: true })).toHaveAttribute("aria-valuenow", "420");
    await expect(page.locator("canvas.context-field")).toHaveCount(0);
    await page.getByRole("button", { name: "打开工作台", exact: true }).click();
    await expect(page.getByRole("button", { name: "Git", exact: true })).toHaveAttribute("aria-pressed", "true");
  });

  test("shows an empty result and survives malformed persisted layout", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("agent.frontend.layout", "{"));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("./#/new");

    await page.getByRole("button", { name: "打开命令面板", exact: true }).click();
    await page.getByLabel("搜索命令", { exact: true }).fill("does-not-exist");
    await expect(page.getByText("没有匹配的命令", { exact: true })).toBeVisible();
    await expect(page.locator("html")).toHaveJSProperty("scrollWidth", 390);
  });
});

test.describe("workspace shell", () => {
  test("opens the workspace plane with five entries and returns focus on close", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("./#/new");

    const openButton = page.getByRole("button", { name: "打开工作台", exact: true });
    await expect(openButton).toBeVisible();
    await openButton.click();

    await expect(page.getByRole("button", { name: "System", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Files", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Git", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Terminal", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Runs", exact: true })).toBeVisible();
    // Default view is System Overview with real health-derived signals.
    await expect(page.getByRole("heading", { name: "系统概览", exact: true })).toBeVisible();
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

test.describe("terminal", () => {
  async function openTerminal(page: Page) {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("./#/new");
    await page.getByRole("button", { name: "打开工作台", exact: true }).click();
    await page.getByRole("button", { name: "Terminal", exact: true }).click();
  }

  test("keeps the terminal disabled until the project CLI enables it", async ({ page }) => {
    await openTerminal(page);
    await expect(page.getByText("Terminal 默认关闭。请在项目终端显式启用：", { exact: true })).toBeVisible();
    await expect(page.getByText("agent config set terminal_enabled true --cwd <workspace>", { exact: true })).toBeVisible();
  });

  test("starts, polls, writes to, and stops one process", async ({ page }) => {
    terminalMode = "idle";
    await openTerminal(page);

    await page.getByLabel("Terminal 程序", { exact: true }).fill("python");
    await page.getByLabel("Terminal 参数", { exact: true }).fill("-c\nprint('ready')");
    await page.getByLabel("Terminal cwd", { exact: true }).fill("scripts");
    await page.getByLabel("Terminal timeout", { exact: true }).fill("30");
    await page.getByRole("button", { name: "启动", exact: true }).click();

    await expect(page.getByLabel("Terminal 输出", { exact: true })).toContainText("ready");
    expect(terminalStartRequest).toEqual({
      argv: ["python", "-c", "print('ready')"],
      cwd: "scripts",
      timeout_seconds: 30,
    });

    await page.reload();
    await page.getByRole("button", { name: "打开工作台", exact: true }).click();
    await page.getByRole("button", { name: "Terminal", exact: true }).click();
    await expect(page.getByText("running", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Terminal 输出", { exact: true })).toContainText("ready");

    await page.getByLabel("Terminal stdin", { exact: true }).fill("hello");
    await page.getByRole("dialog", { name: "工作台", exact: true }).getByRole("button", { name: "发送", exact: true }).click();
    await expect.poll(() => terminalInputRequests).toEqual([{ terminal_id: "terminal_mock", data: "hello" }]);
    await expect(page.getByLabel("Terminal 输出", { exact: true })).toContainText("hello");

    await page.getByRole("button", { name: "停止", exact: true }).click();
    await expect(page.getByText("stopped", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Terminal 输出", { exact: true })).toContainText("Process stopped.");
    expect(terminalStopRequests).toBe(1);
  });

  test("surfaces terminal refresh failures", async ({ page }) => {
    terminalMode = "error";
    await openTerminal(page);
    await expect(page.getByText("Terminal status failed.", { exact: true })).toBeVisible();
  });
});

test.describe("git", () => {
  async function openGit(page: Page) {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("./#/new");
    await page.getByRole("button", { name: "打开工作台", exact: true }).click();
    await page.getByRole("button", { name: "Git", exact: true }).click();
  }

  test("switches staged and unstaged diffs without requesting untracked files", async ({ page }) => {
    await openGit(page);

    await expect(page.getByText("状态项至少 5 条，仅显示前 5 条。", { exact: true })).toBeVisible();
    await expect(page.getByText("rename old.txt", { exact: false })).toBeVisible();
    await expect(page.getByText("conflict", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: /src\/app\.py staged unstaged/ }).click();
    await expect(page.locator(".git-diff")).toContainText("+worktree line");
    await page.getByRole("button", { name: "Staged", exact: true }).click();
    await expect(page.locator(".git-diff")).toContainText("+staged line");
    await expect(page.getByText("Diff 已截断", { exact: true })).toBeVisible();

    const beforeUntracked = gitDiffRequests.length;
    await page.getByRole("button", { name: /notes ü space\.txt untracked/ }).click();
    await expect(page.getByText("Untracked 文件没有 Git diff；请到 Files 中查看内容。", { exact: true })).toBeVisible();
    await expect.poll(() => gitDiffRequests.length).toBe(beforeUntracked);

    await page.getByRole("button", { name: /empty\.txt staged/ }).click();
    await expect(page.getByText("该区域没有可显示的差异。", { exact: true })).toBeVisible();
    expect(gitDiffRequests).toContainEqual({ path: "src/app.py", area: "unstaged" });
    expect(gitDiffRequests).toContainEqual({ path: "src/app.py", area: "staged" });
  });

  test("shows repository, clean, status error, and diff error states", async ({ page }) => {
    gitStatusMode = "nonrepo";
    await openGit(page);
    await expect(page.getByText("请将工作区打开到 Git 仓库根目录。", { exact: true })).toBeVisible();

    gitStatusMode = "clean";
    await page.getByRole("button", { name: "刷新 Git 状态", exact: true }).click();
    await expect(page.getByText("工作区干净。", { exact: true })).toBeVisible();

    gitStatusMode = "error";
    await page.getByRole("button", { name: "刷新 Git 状态", exact: true }).click();
    await expect(page.getByText("Git status failed.", { exact: true })).toBeVisible();

    gitStatusMode = "diff-error";
    await page.getByRole("button", { name: "刷新 Git 状态", exact: true }).click();
    await page.getByRole("button", { name: /broken\.txt unstaged/ }).click();
    await expect(page.getByText("Git diff failed.", { exact: true })).toBeVisible();
  });
});

test.describe("files", () => {
  async function openFiles(page: Page) {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("./#/new");
    await page.getByRole("button", { name: "打开工作台", exact: true }).click();
    await page.getByRole("button", { name: "Files", exact: true }).click();
  }

  async function replaceDesktopEditor(page: Page, value: string) {
    await page.locator(".monaco-editor").click({ position: { x: 180, y: 24 } });
    await page.keyboard.press("Control+a");
    await page.keyboard.insertText(value);
  }

  test("browses directories and previews a text file", async ({ page }) => {
    const editorWorkerRequest = page.waitForRequest((request) => request.url().includes("editor.worker"));
    await openFiles(page);

    await expect(page.getByRole("button", { name: "src", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "src", exact: true }).click();
    await expect(page.getByRole("button", { name: "app.py", exact: true })).toBeVisible();

    await page.getByRole("button", { name: "返回上级", exact: true }).click();
    await page.getByRole("button", { name: "README.md", exact: true }).click();
    await expect(page.getByText("Hello", { exact: false })).toBeVisible();
    await expect(editorWorkerRequest).resolves.toBeDefined();
  });

  test("edits and saves through snapshot confirmation", async ({ page }) => {
    await openFiles(page);
    await page.getByRole("button", { name: "README.md", exact: true }).click();
    await page.getByRole("button", { name: "编辑", exact: true }).click();

    await replaceDesktopEditor(page, "# Readme\nHello world");
    await page.getByRole("button", { name: "保存", exact: true }).click();

    // Confirmation must spell out path, byte count and snapshot before writing.
    const confirm = page.getByRole("dialog", { name: "确认保存", exact: true });
    await expect(confirm).toBeVisible();
    await expect(confirm.getByText("README.md", { exact: false })).toBeVisible();
    await expect(confirm.getByText("将创建 snapshot", { exact: false })).toBeVisible();
    await page.getByRole("button", { name: "确认保存", exact: true }).click();

    await expect(page.getByText("已保存", { exact: false })).toBeVisible();
  });

  test("keeps chat usable beside tools and preserves drafts across modality changes", async ({ page }) => {
    await openFiles(page);
    const panel = page.getByRole("dialog", { name: "工作台", exact: true });
    const composer = page.getByLabel("向 Agent 发送消息", { exact: true });
    await composer.fill("Keep this chat draft");
    await expect(panel).toBeVisible();
    expect(await panel.evaluate((node) => node.matches(":modal"))).toBe(false);
    const chatBounds = await page.locator(".chat-stage").boundingBox();
    const panelBounds = await panel.boundingBox();
    expect(chatBounds!.x + chatBounds!.width).toBeLessThanOrEqual(panelBounds!.x + 1);
    await page.getByRole("button", { name: "README.md", exact: true }).click();
    await page.getByRole("button", { name: "编辑", exact: true }).click();
    await replaceDesktopEditor(page, "preserved file draft");
    const editor = await page.locator(".monaco-editor").elementHandle();
    await page.setViewportSize({ width: 1000, height: 900 });
    await expect.poll(() => panel.evaluate((node) => node.matches(":modal"))).toBe(true);
    expect(await editor!.evaluate((node) => node.isConnected)).toBe(true);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByRole("textbox", { name: "文件编辑器", exact: true })).toHaveValue("preserved file draft");
    await page.getByRole("button", { name: "保存", exact: true }).click();
    const confirm = page.getByRole("dialog", { name: "确认保存", exact: true });
    await expect(confirm).toBeVisible();
    await page.setViewportSize({ width: 1280, height: 900 });
    await expect.poll(() => panel.evaluate((node) => node.matches(":modal"))).toBe(false);
    expect(await confirm.evaluate((node) => node.matches(":modal") && node.contains(document.activeElement))).toBe(true);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect.poll(() => panel.evaluate((node) => node.matches(":modal"))).toBe(true);
    expect(await confirm.evaluate((node) => node.matches(":modal") && node.contains(document.activeElement))).toBe(true);
    await page.keyboard.press("Escape");
    await expect(confirm).toBeHidden();
    await expect(panel).toBeVisible();
    await page.setViewportSize({ width: 1440, height: 900 });
    await expect.poll(() => panel.evaluate((node) => node.matches(":modal"))).toBe(false);
    await expect(page.locator(".view-lines")).toContainText("preserved file draft");
    await expect(composer).toHaveValue("Keep this chat draft");
    await composer.fill("Chat remains interactive");
    await expect(panel).toBeVisible();
  });

  test("keeps truncated files read-only", async ({ page }) => {
    await openFiles(page);
    await page.getByRole("button", { name: "big.txt", exact: true }).click();

    await expect(page.getByText("文件已截断", { exact: false })).toBeVisible();
    // A truncated file must never expose an edit or save affordance.
    await expect(page.getByRole("button", { name: "编辑", exact: true })).toHaveCount(0);
  });

  test("surfaces backend errors when a file cannot be opened", async ({ page }) => {
    await openFiles(page);
    await page.getByRole("button", { name: "missing.txt", exact: true }).click();

    await expect(page.getByText("File not found: missing.txt", { exact: false })).toBeVisible();
  });

  test("guards unsaved edits when closing the workspace", async ({ page }) => {
    await openFiles(page);
    await page.getByRole("button", { name: "README.md", exact: true }).click();
    await page.getByRole("button", { name: "编辑", exact: true }).click();
    await replaceDesktopEditor(page, "# Readme\nDirty edit");

    expect(await page.evaluate(() => !window.dispatchEvent(new Event("beforeunload", { cancelable: true })))).toBe(true);

    // The editor consumes Escape; closing from the panel must still guard edits.
    await page.keyboard.press("Escape");
    await expect(page.locator(".view-lines")).toContainText("Dirty edit");
    await page.getByRole("button", { name: "关闭工作台", exact: true }).focus();
    await page.keyboard.press("Escape");
    const guard = page.getByRole("dialog", { name: "未保存修改", exact: true });
    await expect(guard).toBeVisible();

    // Continue editing keeps the workspace open with the buffer intact.
    await page.getByRole("button", { name: "继续编辑", exact: true }).click();
    await expect(page.locator(".view-lines")).toContainText("Dirty edit");

    // Discarding via the guard closes the workspace.
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "丢弃并继续", exact: true }).click();
    await expect(page.getByRole("button", { name: "System", exact: true })).toHaveCount(0);
  });

  test("guards unsaved edits when a command switches the workspace view", async ({ page }) => {
    await openFiles(page);
    await page.getByRole("button", { name: "README.md", exact: true }).click();
    await page.getByRole("button", { name: "编辑", exact: true }).click();
    await replaceDesktopEditor(page, "unsaved command draft");

    const switchToGit = async () => {
      await page.getByRole("button", { name: "打开命令面板", exact: true }).click();
      await page.getByLabel("搜索命令", { exact: true }).fill("打开 Git");
      await page.getByRole("option", { name: /打开 Git/ }).click();
    };

    await switchToGit();
    await expect(page.getByRole("dialog", { name: "未保存修改", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "继续编辑", exact: true }).click();
    await expect(page.locator(".view-lines")).toContainText("unsaved command draft");
    await expect(page.getByRole("button", { name: "Files", exact: true })).toHaveAttribute("aria-pressed", "true");

    await switchToGit();
    await page.getByRole("button", { name: "丢弃并继续", exact: true }).click();
    await expect(page.getByRole("button", { name: "Git", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".view-lines")).toHaveCount(0);
  });

  test("keeps the dirty buffer when save fails", async ({ page }) => {
    await openFiles(page);
    await page.getByRole("button", { name: "README.md", exact: true }).click();
    await page.getByRole("button", { name: "编辑", exact: true }).click();
    await replaceDesktopEditor(page, "reject save");
    await page.keyboard.press("Control+s");
    await expect(page.getByRole("dialog", { name: "确认保存", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "确认保存", exact: true }).click();

    await expect(page.getByText("Save rejected by fixture.", { exact: true })).toBeVisible();
    await expect(page.locator(".view-lines")).toContainText("reject save");
    await expect(page.getByLabel("已修改", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "保存", exact: true })).toBeEnabled();
  });

  test("keeps independent dirty buffers across tabs and guards dirty tab close", async ({ page }) => {
    await openFiles(page);
    await page.getByRole("button", { name: "README.md", exact: true }).click();
    await page.getByRole("button", { name: "编辑", exact: true }).click();
    await replaceDesktopEditor(page, "README dirty");

    await page.getByRole("button", { name: "src", exact: true }).click();
    await page.getByRole("button", { name: "app.py", exact: true }).click();
    await page.getByRole("button", { name: "编辑", exact: true }).click();
    await replaceDesktopEditor(page, "app dirty");

    await page.getByRole("tab", { name: "README.md", exact: true }).click();
    await expect(page.locator(".view-lines")).toContainText("README dirty");
    await page.locator(".monaco-editor").click();
    await page.keyboard.press("Control+End");
    await page.keyboard.type("!?");
    await expect(page.locator(".view-lines")).toContainText("README dirty!?");
    await page.getByRole("tab", { name: "app.py", exact: true }).click();
    await page.getByRole("button", { name: "关闭 src/app.py", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "未保存修改", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "继续编辑", exact: true }).click();
    await expect(page.locator(".view-lines")).toContainText("app dirty");

    await page.getByRole("button", { name: "关闭 src/app.py", exact: true }).click();
    await page.getByRole("button", { name: "丢弃修改", exact: true }).click();
    await expect(page.getByRole("tab", { name: "app.py", exact: true })).toHaveCount(0);
    await expect(page.locator(".view-lines")).toContainText("README dirty");
  });

  test("searches recursively, reports bounds, and jumps to a matching line", async ({ page }) => {
    await openFiles(page);
    const search = page.getByRole("searchbox", { name: "递归搜索工作区", exact: true });
    await search.fill("needle");
    await search.press("Enter");

    await expect(page.getByText("已扫描 10000 个文件，结果至少 52 条", { exact: false })).toBeVisible();
    await expect(page.getByText("仅显示前 2 条", { exact: false })).toBeVisible();
    await page.getByRole("button", { name: "src/app.py 第 2 行", exact: true }).click();
    await expect(page.getByRole("tab", { name: "app.py", exact: true })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByText("已跳转到第 2 行", { exact: true })).toBeVisible();

    await search.fill("empty");
    await search.press("Enter");
    await expect(page.getByText("未找到匹配项。", { exact: true })).toBeVisible();

    await search.fill("broken");
    await search.press("Enter");
    await expect(page.getByText("Workspace search failed.", { exact: true })).toBeVisible();
  });

  test("uses the native editor fallback on narrow screens and saves with Ctrl+S", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("./#/new");
    await page.getByRole("button", { name: "打开工作台", exact: true }).click();
    await page.getByRole("button", { name: "Files", exact: true }).click();
    await page.getByRole("button", { name: "README.md", exact: true }).click();
    await page.getByRole("button", { name: "编辑", exact: true }).click();

    const editor = page.getByRole("textbox", { name: "文件编辑器", exact: true });
    await expect(editor).toHaveClass(/files-editor-native/);
    await expect(page.locator(".monaco-editor")).toHaveCount(0);
    await editor.fill("mobile dirty");
    await editor.press("Control+s");
    await page.getByRole("button", { name: "确认保存", exact: true }).click();

    expect(savedFileRequests).toEqual([{ path: "README.md", content: "mobile dirty" }]);
  });
});

test.describe("runs", () => {
  async function openRuns(page: Page) {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("./#/new");
    await page.getByRole("button", { name: "打开工作台", exact: true }).click();
    await page.getByRole("button", { name: "Runs", exact: true }).click();
  }

  test("opens detail and renders review, replay and snapshots", async ({ page }) => {
    await openRuns(page);
    await page.getByRole("button", { name: "run_e2e", exact: true }).click();

    await expect(page.getByRole("heading", { name: "结果核对", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "执行回放", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "文件快照", exact: true })).toBeVisible();
    await expect(page.getByText("只读", { exact: true }).first()).toBeVisible();
  });

  test("replay filters by terminal state", async ({ page }) => {
    await openRuns(page);
    await page.getByRole("button", { name: "run_e2e", exact: true }).click();

    const steps = page.locator(".replay-steps");
    await expect(steps.getByText("write_file", { exact: true })).toBeVisible();
    await page.getByLabel("终态过滤", { exact: true }).selectOption("terminal");
    await expect(steps.getByText("write_file", { exact: true })).toHaveCount(0);
    await expect(steps.getByText("done", { exact: true })).toBeVisible();
  });

  test("shows diff and confirms snapshot restore", async ({ page }) => {
    await openRuns(page);
    await page.getByRole("button", { name: "run_e2e", exact: true }).click();

    await page.getByRole("button", { name: "查看 diff", exact: true }).click();
    await expect(page.getByText("+new", { exact: false })).toBeVisible();

    await page.getByRole("button", { name: "恢复", exact: true }).click();
    const confirm = page.getByRole("dialog", { name: "确认恢复", exact: true });
    await expect(confirm).toBeVisible();
    await expect(confirm.getByText("snap_readme_1", { exact: false })).toBeVisible();
    await page.getByRole("button", { name: "确认恢复", exact: true }).click();

    await expect(page.getByText("已恢复", { exact: false })).toBeVisible();
  });

  test("filters the run index by status", async ({ page }) => {
    await openRuns(page);
    const index = page.locator(".runs-index");
    await expect(index.getByRole("button", { name: "run_e2e", exact: true })).toBeVisible();

    await page.getByLabel("状态过滤", { exact: true }).selectOption("failed");
    await expect(index.getByRole("button", { name: "run_e2e", exact: true })).toHaveCount(0);
    await expect(index.getByRole("button", { name: "run_attn", exact: true })).toBeVisible();
  });
});

test.describe("system", () => {
  async function openSystem(page: Page) {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("./#/new");
    await page.getByRole("button", { name: "打开工作台", exact: true }).click();
  }

  test("renders readiness, risk, memory and tools as readable detail", async ({ page }) => {
    await openSystem(page);

    await expect(page.getByRole("heading", { name: "配置检查", exact: true })).toBeVisible();
    await expect(page.getByText("Settings are readable.", { exact: false })).toBeVisible();
    await expect(page.getByRole("heading", { name: "工作区风险", exact: true })).toBeVisible();

    // Memory stays read-only: entries are visible, no accept/reject controls exist.
    await expect(page.getByRole("heading", { name: "记忆审阅", exact: true })).toBeVisible();
    await expect(page.getByText("候选记忆：项目使用 pytest。", { exact: false })).toBeVisible();
    await expect(page.getByRole("button", { name: "接受", exact: true })).toHaveCount(0);

    await expect(page.getByRole("heading", { name: "可用工具", exact: true })).toBeVisible();
    await expect(page.getByText("read_file", { exact: false }).first()).toBeVisible();
  });

  test("keeps secrets and non-whitelisted keys out of the settings form", async ({ page }) => {
    await openSystem(page);

    await expect(page.getByLabel("model", { exact: true })).toBeVisible();
    await expect(page.locator('input[type="password"]')).toHaveCount(0);
    await expect(page.getByLabel("allowed_commands", { exact: true })).toHaveCount(0);
    await expect(page.getByLabel("base_url", { exact: true })).toHaveCount(0);
    // sandbox must not offer the danger value the backend rejects.
    await expect(page.getByLabel("sandbox", { exact: true }).locator("option")).toHaveText(["read-only", "workspace-write"]);
    await expect(page.getByLabel("approval", { exact: true }).locator("option")).toHaveText(["risky-confirm", "always"]);
  });

  test("saves only the changed whitelist keys", async ({ page }) => {
    await openSystem(page);

    await page.getByLabel("mode", { exact: true }).selectOption("auto");
    await page.getByRole("button", { name: "保存设置", exact: true }).click();

    await expect(page.getByText("设置已保存。", { exact: true })).toBeVisible();
    expect(savedConfigUpdates).toEqual({ mode: "auto" });
  });

  test("keeps the dirty draft when the server rejects the save", async ({ page }) => {
    await openSystem(page);
    rejectConfigSave = true;

    await page.getByLabel("model", { exact: true }).fill("bogus-model");
    await page.getByRole("button", { name: "保存设置", exact: true }).click();

    await expect(page.getByText("mode must be step, guided, auto, or plan-first.", { exact: false })).toBeVisible();
    await expect(page.getByLabel("model", { exact: true })).toHaveValue("bogus-model");
  });

  test("opens a run detail from the resource list", async ({ page }) => {
    await openSystem(page);

    await page.getByRole("heading", { name: "工作区资源", exact: true }).scrollIntoViewIfNeeded();
    await page.getByRole("button", { name: /run_e2e/ }).last().click();

    // Cross-view jump lands on the Runs detail for that run.
    await expect(page.getByRole("heading", { name: "结果核对", exact: true })).toBeVisible();
  });
});

test.describe("workspace layout and a11y", () => {
  async function openWorkspace(page: Page, view?: "Files" | "Git" | "Terminal" | "Runs" | "System") {
    await page.goto("./#/new");
    await page.getByRole("button", { name: "打开工作台", exact: true }).click();
    if (view) await page.getByRole("button", { name: view, exact: true }).click();
  }

  async function pageOverflows(page: Page) {
    return page.evaluate(() => document.body.scrollWidth > window.innerWidth);
  }

  for (const width of [1440, 1280, 390, 320]) {
    test(`keeps the workspace free of horizontal overflow at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await openWorkspace(page, "System");
      expect(await pageOverflows(page)).toBe(false);

      await page.getByRole("button", { name: "Files", exact: true }).click();
      await expect(page.getByRole("button", { name: "README.md", exact: true })).toBeVisible();
      expect(await pageOverflows(page)).toBe(false);

      await page.getByRole("button", { name: "Git", exact: true }).click();
      await expect(page.getByText("状态项至少 5 条", { exact: false })).toBeVisible();
      expect(await pageOverflows(page)).toBe(false);

      await page.getByRole("button", { name: "Terminal", exact: true }).click();
      await expect(page.getByText("Terminal 默认关闭。请在项目终端显式启用：", { exact: true })).toBeVisible();
      expect(await pageOverflows(page)).toBe(false);

      await page.getByRole("button", { name: "Runs", exact: true }).click();
      await page.getByRole("button", { name: "run_e2e", exact: true }).click();
      await page.getByRole("button", { name: "查看 diff", exact: true }).click();
      await expect(page.getByText("+new", { exact: false })).toBeVisible();
      // The diff scrolls inside its own container instead of stretching the page.
      expect(await pageOverflows(page)).toBe(false);
    });
  }

  // The user-reported defect: with realistic long titles / run ids the column content
  // painted over the neighbouring column instead of ellipsizing inside its own box.
  test("never paints one column's text over its neighbour", async ({ page }) => {
    await page.setViewportSize({ width: 1712, height: 1080 });
    await openWorkspace(page, "System");
    await page.getByRole("heading", { name: "工作区资源", exact: true }).scrollIntoViewIfNeeded();

    const resourceOverlap = await page.evaluate(() => {
      const grid = document.querySelector(".resource-grid");
      if (!grid) return "missing";
      const columns = [...grid.children].map((column) => column.getBoundingClientRect());
      const columnsOverlap = columns.some((box, index) =>
        columns.slice(index + 1).some((other) => box.right > other.left && box.left < other.right && box.bottom > other.top && box.top < other.bottom),
      );
      // Any text wider than its own box must be clipped, never painted outside it.
      const spillingText = [...grid.querySelectorAll<HTMLElement>(".resource-link > span:first-child")]
        .filter((span) => span.scrollWidth > span.clientWidth && getComputedStyle(span).overflow === "visible");
      return { columnsOverlap, spilling: spillingText.length };
    });
    expect(resourceOverlap).toEqual({ columnsOverlap: false, spilling: 0 });

    await page.getByRole("button", { name: "Runs", exact: true }).click();
    await page.getByRole("button", { name: "run_20260725_045603_309947", exact: true }).click();
    await expect(page.getByRole("heading", { name: "结果核对", exact: true })).toBeVisible();

    const runsOverlap = await page.evaluate(() => {
      const track = document.querySelector(".runs-index-track")?.getBoundingClientRect();
      const detail = document.querySelector(".runs-detail")?.getBoundingClientRect();
      if (!track || !detail) return "missing";
      return {
        columnsOverlap: track.right > detail.left && track.bottom > detail.top,
        indexBlownOut: (document.querySelector(".runs-index") as HTMLElement).scrollWidth
          > (document.querySelector(".runs-index") as HTMLElement).clientWidth,
      };
    });
    expect(runsOverlap).toEqual({ columnsOverlap: false, indexBlownOut: false });
  });

  test("truncates long paths but keeps the full value in title", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openWorkspace(page, "Files");

    const entry = page.locator(".files-entry-name").filter({ hasText: "an-extremely-long" });
    await expect(entry).toHaveAttribute("title", /deeply\\nested\\windows\\path/);
    const clipped = await entry.evaluate((el) => el.scrollWidth > el.clientWidth);
    expect(clipped).toBe(true);
  });

  test("drives the whole workspace from the keyboard", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("./#/new");

    // Open via keyboard, then reach the view tabs and the close control by tabbing.
    const opener = page.getByRole("button", { name: "打开工作台", exact: true });
    await opener.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "系统概览", exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Runs", exact: true }).focus();
    await page.keyboard.press("Enter");
    await page.getByRole("button", { name: "run_e2e", exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "结果核对", exact: true })).toBeVisible();

    // Escape closes the plane and focus returns to the opener.
    await page.keyboard.press("Escape");
    await expect(opener).toBeFocused();
  });

  test("gives every workspace icon button an accessible name", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openWorkspace(page);

    const unnamed = await page.locator(".workspace-plane button").evaluateAll((buttons) =>
      buttons.filter((button) => !(button.getAttribute("aria-label") || button.textContent || "").trim()).length,
    );
    expect(unnamed).toBe(0);
  });

  test("drops the plane spring under reduced motion", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openWorkspace(page);

    const plane = page.locator(".workspace-plane");
    await expect(plane).toBeVisible();
    // reduced-motion is enabled in beforeEach: the plane must already be settled at x=0.
    const transform = await plane.evaluate((el) => getComputedStyle(el).transform);
    expect(transform === "none" || transform.endsWith(", 0, 0)")).toBe(true);
    // Status text is never reduced along with motion.
    await expect(page.getByText("FakeLLM ready.", { exact: false })).toBeVisible();
  });

  test("keeps workspace interactions inside the long-task budget", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("./#/new");

    await page.evaluate(() => {
      const store: number[] = [];
      (window as unknown as { __longTasks: number[] }).__longTasks = store;
      const Observer = window.PerformanceObserver;
      if (Observer && Observer.supportedEntryTypes.includes("longtask")) {
        new Observer((list) => list.getEntries().forEach((entry) => store.push(entry.duration)))
          .observe({ entryTypes: ["longtask"] });
      }
    });

    await page.getByRole("button", { name: "打开工作台", exact: true }).click();
    await page.getByRole("button", { name: "Runs", exact: true }).click();
    await page.getByLabel("状态过滤", { exact: true }).selectOption("failed");
    await page.getByLabel("状态过滤", { exact: true }).selectOption("");
    await page.getByRole("button", { name: "Files", exact: true }).click();
    await page.getByRole("button", { name: "System", exact: true }).click();

    const longest = await page.evaluate(() => {
      const tasks = (window as unknown as { __longTasks: number[] }).__longTasks;
      return tasks.length ? Math.max(...tasks) : 0;
    });
    expect(longest).toBeLessThan(100);
  });
});

const visualVariants = [
  { name: "b-dark-desktop", width: 1440, height: 900, theme: "b", mode: "dark" },
  { name: "b-light-desktop", width: 1440, height: 900, theme: "b", mode: "light" },
  { name: "b-dark-mobile-390", width: 390, height: 844, theme: "b", mode: "dark" },
  { name: "b-dark-mobile-320", width: 320, height: 568, theme: "b", mode: "dark" },
  { name: "a-dark-desktop", width: 1440, height: 900, theme: "a", mode: "dark" },
  { name: "a-light-desktop", width: 1440, height: 900, theme: "a", mode: "light" },
  { name: "c-light-desktop", width: 1440, height: 900, theme: "c", mode: "light" },
  { name: "c-dark-desktop", width: 1440, height: 900, theme: "c", mode: "dark" },
] as const;

for (const variant of visualVariants) {
  test(`visual ${variant.name}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: variant.width, height: variant.height });
    await page.goto("./#/new");
    await page.getByLabel("主题", { exact: true }).selectOption(variant.theme);
    await page.getByLabel("显示模式", { exact: true }).selectOption(variant.mode);
    // Canvas orbs paint via requestAnimationFrame, which `animations: "disabled"`
    // does not stop; reduced motion pins them to one deterministic frame.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.screenshot({ path: testInfo.outputPath("review.png"), animations: "disabled" });
    await expect(page).toHaveScreenshot(`${variant.name}.png`, { animations: "disabled" });

    const dimensions = await page.evaluate(() => ({ width: window.innerWidth, scrollWidth: document.body.scrollWidth }));
    expect(dimensions.scrollWidth).toBe(dimensions.width);
  });
}

for (const variant of [
  { width: 1440, mode: "dark" }, { width: 1440, mode: "light" }, { width: 390, mode: "dark" },
] as const) {
  test(`visual execution ${variant.width} ${variant.mode}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: variant.width, height: 900 });
    await page.goto("./#/new");
    await page.getByLabel("显示模式", { exact: true }).selectOption(variant.mode);
    await startTurn(page);
    await emit(page, "approval_required", {
      event: "approval_required", sequence: 0, elapsed_ms: 12, run_id: "run_orb", action_index: 1,
      action: "write_file", message: "更新工作区说明", args: { path: "README.md" }, reason: "写入前请确认目标文件。",
    });
    await page.getByRole("button", { name: "阶段详情", exact: true }).click();
    await expect(page.getByRole("region", { name: "阶段详情", exact: true })).toContainText("approval_required");
    await page.clock.pauseAt(new Date());
    await page.screenshot({ path: testInfo.outputPath("review.png"), animations: "disabled" });
    await expect(page).toHaveScreenshot(`execution-${variant.width}-${variant.mode}.png`, { animations: "disabled", mask: [page.locator(".approval-heading time")] });
  });
}

// Deterministic baselines for the workspace plane: three states across four viewports.
const workspaceVisuals = [
  { name: "workspace-system-dark-1440", width: 1440, height: 900, mode: "dark", state: "system" },
  { name: "workspace-files-light-1440", width: 1440, height: 900, mode: "light", state: "files" },
  { name: "workspace-runs-dark-390", width: 390, height: 844, mode: "dark", state: "run-attention" },
  { name: "workspace-system-dark-320", width: 320, height: 568, mode: "dark", state: "system" },
] as const;

for (const variant of workspaceVisuals) {
  test(`visual ${variant.name}`, async ({ page }) => {
    // Masking hides the clock pixels, but only fixed time keeps its layout width deterministic.
    await page.clock.setFixedTime(new Date("2026-07-25T12:34:56"));
    await page.setViewportSize({ width: variant.width, height: variant.height });
    await page.goto("./#/new");
    await page.getByLabel("显示模式", { exact: true }).selectOption(variant.mode);
    await page.getByRole("button", { name: "打开工作台", exact: true }).click();

    if (variant.state === "files") {
      await page.getByRole("button", { name: "Files", exact: true }).click();
      await page.getByRole("button", { name: "README.md", exact: true }).click();
      await page.getByRole("button", { name: "编辑", exact: true }).click();
      await expect(page.getByRole("textbox", { name: "文件编辑器", exact: true })).toBeVisible();
    } else if (variant.state === "run-attention") {
      await page.getByRole("button", { name: "Runs", exact: true }).click();
      await page.getByRole("button", { name: "run_attn", exact: true }).click();
      await expect(page.getByRole("heading", { name: "失败详情", exact: true })).toBeVisible();
    } else {
      await expect(page.getByRole("heading", { name: "配置检查", exact: true })).toBeVisible();
    }

    // Canvas orbs paint via requestAnimationFrame, which `animations: "disabled"`
    // does not stop; reduced motion pins them to one deterministic frame.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await expect(page).toHaveScreenshot(`${variant.name}.png`, {
      animations: "disabled",
      // Keep wall-clock text out of the approved image.
      mask: [page.locator(".workspace-refresh-time")],
    });
    const dimensions = await page.evaluate(() => ({ width: window.innerWidth, scrollWidth: document.body.scrollWidth }));
    expect(dimensions.scrollWidth).toBe(dimensions.width);
  });
}

for (const variant of [
  { name: "workspace-terminal-disabled-dark-1440", width: 1440, height: 900, running: false },
  { name: "workspace-terminal-running-dark-390", width: 390, height: 844, running: true },
] as const) {
  test(`visual ${variant.name}`, async ({ page }) => {
    await page.clock.setFixedTime(new Date("2026-07-25T12:34:56"));
    await page.setViewportSize({ width: variant.width, height: variant.height });
    terminalMode = variant.running ? "idle" : "disabled";
    await page.goto("./#/new");
    await page.getByLabel("显示模式", { exact: true }).selectOption("dark");
    await page.getByRole("button", { name: "打开工作台", exact: true }).click();
    await page.getByRole("button", { name: "Terminal", exact: true }).click();
    if (variant.running) {
      await page.getByLabel("Terminal 程序", { exact: true }).fill("python");
      await page.getByLabel("Terminal 参数", { exact: true }).fill("-c\nprint('ready')");
      await page.getByRole("button", { name: "启动", exact: true }).click();
      await expect(page.getByLabel("Terminal 输出", { exact: true })).toContainText("ready");
    } else {
      await expect(page.getByText("Terminal 默认关闭。请在项目终端显式启用：", { exact: true })).toBeVisible();
    }

    // Canvas orbs paint via requestAnimationFrame, which `animations: "disabled"`
    // does not stop; reduced motion pins them to one deterministic frame.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await expect(page).toHaveScreenshot(`${variant.name}.png`, {
      animations: "disabled",
      mask: [page.locator(".workspace-refresh-time")],
    });
    const dimensions = await page.evaluate(() => ({ width: window.innerWidth, scrollWidth: document.body.scrollWidth }));
    expect(dimensions.scrollWidth).toBe(dimensions.width);
  });
}

for (const variant of [
  { name: "command-palette-dark-1440", width: 1440, height: 900 },
  { name: "command-palette-dark-390", width: 390, height: 844 },
] as const) {
  test(`visual ${variant.name}`, async ({ page }) => {
    await page.setViewportSize({ width: variant.width, height: variant.height });
    await page.goto("./#/new");
    await page.getByLabel("显示模式", { exact: true }).selectOption("dark");
    await page.getByRole("button", { name: "打开命令面板", exact: true }).click();
    await page.getByLabel("搜索命令", { exact: true }).fill("工作台");
    await expect(page.getByRole("option")).toHaveCount(5);
    // Canvas orbs paint via requestAnimationFrame, which `animations: "disabled"`
    // does not stop; reduced motion pins them to one deterministic frame.
    await page.emulateMedia({ reducedMotion: "reduce" });
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

// Orb state baselines. The 9 indicator states are only visible while a turn is
// pending, so no full-page baseline can ever capture them; each case drives the
// real event path, freezes the canvas with reduced motion, and clips the row that
// holds the orb. Reduced-motion frames were verified to be both distinguishable
// per state and byte-identical across runs before these baselines were adopted.
type OrbCase = {
  state: string;
  container: string;
  drive: (page: Page) => Promise<void>;
};

async function startTurn(page: Page) {
  await page.getByLabel("向 Agent 发送消息", { exact: true }).fill("Orb baseline fixture");
  await page.getByRole("button", { name: "发送", exact: true }).click();
}

async function driveToolStart(page: Page, action: string) {
  await startTurn(page);
  await emit(page, "tool_start", {
    event: "tool_start",
    sequence: 0,
    elapsed_ms: 20,
    run_id: "run_orb",
    action_index: 1,
    action,
    message: `Running ${action}.`,
    args: {},
  });
}

const orbCases: OrbCase[] = [
  {
    state: "solving",
    container: ".live-turn .agent-utterance .utterance-label",
    drive: async (page) => {
      await startTurn(page);
      await emit(page, "model_call_start", { event: "model_call_start", sequence: 0, elapsed_ms: 5 });
    },
  },
  {
    state: "weaving",
    container: ".live-turn .agent-utterance .utterance-label",
    drive: async (page) => {
      await startTurn(page);
      await emit(page, "model_stream_chunk", {
        event: "model_stream_chunk", sequence: 0, elapsed_ms: 8, kind: "thinking", text: "reasoning", chunk_chars: 9,
      });
    },
  },
  {
    state: "composing",
    container: ".live-turn .agent-utterance .utterance-label",
    drive: async (page) => {
      await startTurn(page);
      await emit(page, "model_stream_chunk", {
        event: "model_stream_chunk", sequence: 0, elapsed_ms: 8, kind: "content", text: "answer", chunk_chars: 6,
      });
    },
  },
  { state: "searching", container: ".live-turn .agent-utterance .utterance-label", drive: (page) => driveToolStart(page, "search_files") },
  { state: "shaping", container: ".live-turn .agent-utterance .utterance-label", drive: (page) => driveToolStart(page, "apply_patch") },
  { state: "working", container: ".live-turn .agent-utterance .utterance-label", drive: (page) => driveToolStart(page, "run_command") },
  {
    state: "listening",
    container: ".live-turn .agent-utterance .utterance-label",
    drive: async (page) => {
      await startTurn(page);
      await emit(page, "approval_required", {
        event: "approval_required",
        sequence: 0,
        elapsed_ms: 30,
        run_id: "run_orb",
        action_index: 1,
        action: "run_command",
        message: "Inspect the local workspace.",
        args: { argv: ["git", "status", "--short"] },
        reason: "This action starts a local process.",
      });
    },
  },
  {
    state: "breathing",
    container: ".live-turn .agent-utterance .utterance-label",
    drive: async (page) => {
      await startTurn(page);
      // `error` is deliberately not in TERMINAL_EVENTS, so the live turn survives;
      // `failed` would trigger settleJob and wipe the turn before the button renders.
      await emit(page, "error", { event: "error", sequence: 0, elapsed_ms: 40, error: "fixture failure" });
      // Recovery is transient: it ends the moment the history fetch resolves, so
      // hold that fetch open to keep the phase observable.
      // times: 1 so the delay cannot leak into a later case in the loop below.
      await page.route("**/api/chats/*", async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 10_000));
        await route.fallback();
      }, { times: 1 });
      await page.getByRole("button", { name: "从历史重建", exact: true }).click();
    },
  },
  {
    state: "connecting",
    // The Terminal view's own loading state is a far steadier home for this orb
    // than StatusMark, whose health probe resolves before a screenshot can land.
    container: '.terminal-view p.overview-note[role="status"]',
    drive: async (page) => {
      // The view polls terminal twice on mount; delaying only the first would let
      // the second clear the loading state before the screenshot lands.
      await page.route("**/api/terminal*", async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 10_000));
        await route.fallback();
      });
      await page.getByRole("button", { name: "打开工作台", exact: true }).click();
      await page.getByRole("button", { name: "Terminal", exact: true }).click();
    },
  },
];

// Playwright cannot be made to composite this 20px canvas reliably: a clip of the
// surrounding row drops the canvas pixels entirely, and an element clip returns a
// blank PNG for five of the nine states even while getImageData reports ink. The
// canvas bitmap itself is stable and reproducible, so assert on that instead.
for (const mode of ["dark", "light"] as const) {
  test(`renders a distinct orb per state in ${mode} mode`, async ({ browser }) => {
    test.setTimeout(120_000);
    const frames = new Map<string, string>();
    for (const orbCase of orbCases) {
      // A fresh page per state: the mock backend keeps job state across navigations,
      // so reusing one page lets an earlier turn disable the next composer.
      const context = await browser.newContext();
      const page = await context.newPage();
      await installWorkbenchMocks(page);
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.setViewportSize({ width: 900, height: 700 });
      await page.goto("./#/new");
      await page.getByLabel("显示模式", { exact: true }).selectOption(mode);
      await orbCase.drive(page);
      const canvas = page.locator(`${orbCase.container} canvas`);
      await expect(canvas).toBeVisible();
      await expect.poll(async () => canvas.evaluate((node) => {
        const element = node as HTMLCanvasElement;
        const pixels = element.getContext("2d")?.getImageData(0, 0, element.width, element.height).data;
        if (!pixels) return 0;
        let painted = 0;
        for (let index = 3; index < pixels.length; index += 4) if (pixels[index] !== 0) painted += 1;
        return painted;
      }), { timeout: 10_000 }).toBeGreaterThan(20);
      frames.set(orbCase.state, await canvas.evaluate((node) => (node as HTMLCanvasElement).toDataURL()));
      await context.close();
    }
    expect(frames.size).toBe(orbCases.length);
    // Nine states must paint nine different orbs; a mapping regression that points
    // two phases at one animation collapses this set.
    expect(new Set(frames.values()).size).toBe(orbCases.length);
  });
}
