const state = {
  runs: [],
  selectedRunId: null,
  sessionId: null,
  pendingApproval: null,
  openFilePath: null,
  runRiskFilter: "all",
  selectedDetail: null,
  logFilterText: "",
  logFilterTerminal: "all",
};

const els = {
  workspace: document.querySelector("#workspace-pill"),
  provider: document.querySelector("#provider-chip"),
  model: document.querySelector("#model-chip"),
  providerNotice: document.querySelector("#provider-notice"),
  apiKey: document.querySelector("#api-key-chip"),
  lastRefresh: document.querySelector("#last-refresh-chip"),
  refreshButton: document.querySelector("#refresh-button"),
  runList: document.querySelector("#run-list"),
  summary: document.querySelector("#summary-view"),
  fileEditor: document.querySelector("#file-editor"),
  saveFileButton: document.querySelector("#save-file-button"),
  selectedRunTitle: document.querySelector("#selected-run-title"),
  runState: document.querySelector("#run-state"),
  toolList: document.querySelector("#tool-list"),
  activityLog: document.querySelector("#activity-log"),
  workspaceRiskList: document.querySelector("#workspace-risk-list"),
  memoryReviewList: document.querySelector("#memory-review-list"),
  settingsReadinessList: document.querySelector("#settings-readiness-list"),
  approvalPanel: document.querySelector("#approval-panel"),
  approvalAction: document.querySelector("#approval-action"),
  approvalDetail: document.querySelector("#approval-detail"),
  approveButton: document.querySelector("#approve-button"),
  denyButton: document.querySelector("#deny-button"),
  taskReviewList: document.querySelector("#task-review-list"),
  workflowHintList: document.querySelector("#workflow-hint-list"),
  failureSummaryList: document.querySelector("#failure-summary-list"),
  patchReviewList: document.querySelector("#patch-review-list"),
  failureRecoveryList: document.querySelector("#failure-recovery-list"),
  runReplayList: document.querySelector("#run-replay-list"),
  toolCallList: document.querySelector("#tool-call-list"),
  snapshotList: document.querySelector("#snapshot-list"),
  fileList: document.querySelector("#file-list"),
  runSearch: document.querySelector("#run-search"),
  runRiskFilter: document.querySelector("#run-risk-filter"),
  logFilterText: document.querySelector("#log-filter-text"),
  logFilterTerminal: document.querySelector("#log-filter-terminal"),
  chatForm: document.querySelector("#chat-form"),
  messageInput: document.querySelector("#message-input"),
  sendButton: document.querySelector("#send-button"),
  sessionChip: document.querySelector("#session-chip"),
};

async function loadJson(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${path} failed: ${text}`);
  }
  return response.json();
}

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.error || `${path} failed`);
  }
  return result;
}

async function boot() {
  try {
    addActivityEvent("Opening workspace", "Loading health, tools, runs, and files.");
    const [health, tools, runs] = await Promise.all([
      loadJson("/api/health"),
      loadJson("/api/tools"),
      loadJson("/api/runs"),
    ]);
    renderHealth(health);
    renderTools(tools.tools);
    state.runs = runs.runs;
    renderRuns();
    renderLastRefresh();
    if (state.runs.length > 0) {
      await selectRun(state.runs[0].run_id);
    } else {
      renderEmptyRuns();
    }
    await loadFiles(".");
    addActivityEvent("Workspace ready", "Local state loaded.");
  } catch (error) {
    addActivityEvent("Workspace load failed", error instanceof Error ? error.message : String(error));
    showSummary(error instanceof Error ? error.message : String(error));
  }
}

function renderHealth(health) {
  els.workspace.textContent = health.workspace;
  els.provider.textContent = `provider: ${health.provider}`;
  els.model.textContent = `model: ${health.model}`;
  els.apiKey.textContent = `DeepSeek key: ${health.deepseek_api_key_present ? "present" : "missing"}`;
  els.apiKey.title = `DeepSeek key env: ${health.deepseek_api_key_env}`;
  els.providerNotice.textContent = health.provider_notice || "";
  els.providerNotice.className =
    health.provider === "deepseek" && health.deepseek_api_key_present
      ? "provider-notice ok"
      : "provider-notice warning";
  renderWorkspaceRisk(health.workspace_risk);
  renderMemoryReview(health.memory_review);
  renderSettingsReadiness(health.settings_readiness);
}

function renderWorkspaceRisk(workspaceRisk) {
  if (!workspaceRisk) {
    els.workspaceRiskList.innerHTML = '<div class="empty-state">No workspace risk hints recorded.</div>';
    return;
  }
  const signals = workspaceRisk.signals || {};
  const rows = [
    ["Risk", workspaceRisk.risk_level || "low"],
    ["Summary", workspaceRisk.summary || "No workspace risk summary."],
    [
      "Signals",
      `${signals.uncommitted_files || 0} uncommitted, ${signals.failed_runs || 0} failed run(s), ${signals.snapshots || 0} snapshot(s)`,
    ],
    ["Checks", workspaceRisk.checks?.join(" ") || "No workspace risk action needed."],
  ];
  els.workspaceRiskList.replaceChildren(
    ...rows.map(([label, value]) => {
      const item = document.createElement("article");
      item.className = "trace-item";
      item.innerHTML = `
        <div class="tool-name"></div>
        <div class="trace-meta"></div>
      `;
      item.querySelector(".tool-name").textContent = label;
      item.querySelector(".trace-meta").textContent = value;
      return item;
    }),
  );
}

function renderMemoryReview(memoryReview) {
  if (!memoryReview) {
    els.memoryReviewList.innerHTML = '<div class="empty-state">No memory review recorded.</div>';
    return;
  }
  const rows = [
    ["Pending candidates", `${memoryReview.pending_count || 0}`],
    ["Active entries", `${memoryReview.active_count || 0}`],
    ["Checks", memoryReview.checks?.join(" ") || "No memory review action needed"],
  ];
  const items = rows.map(([label, value]) => traceItem(label, value));
  for (const candidate of memoryReview.candidates || []) {
    items.push(traceItem(`candidate ${candidate.candidate_id}`, `${candidate.source_run_id}: ${candidate.source_excerpt}`));
  }
  for (const entry of memoryReview.entries || []) {
    items.push(traceItem(`entry ${entry.entry_id}`, `${entry.source_run_id}: ${entry.source_excerpt}`));
  }
  els.memoryReviewList.replaceChildren(...items);
}

function renderSettingsReadiness(settingsReadiness) {
  if (!settingsReadiness) {
    els.settingsReadinessList.innerHTML = '<div class="empty-state">No settings readiness recorded.</div>';
    return;
  }
  const rows = [
    ["Status", settingsReadiness.status || "ready"],
    ["Provider", settingsReadiness.provider || "fake"],
    ["Model", settingsReadiness.model || "unknown"],
    ["DeepSeek key", settingsReadiness.deepseek_api_key_present ? "present" : "missing"],
    ["Loaded files", settingsReadiness.loaded_files?.join(", ") || "none"],
    ["Warnings", settingsReadiness.warnings?.join(" ") || "none"],
    ["Checks", settingsReadiness.checks?.join(" ") || "Settings are readable."],
  ];
  els.settingsReadinessList.replaceChildren(...rows.map(([label, value]) => traceItem(label, value)));
}

function traceItem(label, value) {
  const item = document.createElement("article");
  item.className = "trace-item";
  item.innerHTML = `
    <div class="tool-name"></div>
    <div class="trace-meta"></div>
  `;
  item.querySelector(".tool-name").textContent = label;
  item.querySelector(".trace-meta").textContent = value;
  return item;
}

function renderLastRefresh(date = new Date()) {
  els.lastRefresh.textContent = `Last refresh: ${date.toLocaleTimeString()}`;
}

async function refreshWorkbench({ refreshSelectedRun = true, log = false } = {}) {
  try {
    const [health, runs] = await Promise.all([loadJson("/api/health"), loadJson("/api/runs")]);
    renderHealth(health);
    state.runs = runs.runs;
    renderRuns();
    renderLastRefresh();
    if (refreshSelectedRun && shouldRefreshSelectedRun()) {
      await selectRun(state.selectedRunId);
    }
    if (log) {
      addActivityEvent("Workbench refreshed", "Health and runs updated.");
    }
  } catch (error) {
    if (log) {
      addActivityEvent("Refresh failed", error instanceof Error ? error.message : String(error));
    }
  }
}

function shouldRefreshSelectedRun() {
  return Boolean(state.selectedRunId) && !(state.openFilePath || state.pendingApproval);
}

function renderTools(tools) {
  els.toolList.replaceChildren(
    ...tools.map((tool) => {
      const item = document.createElement("article");
      item.className = "tool-item";
      item.innerHTML = `
        <div class="tool-name"></div>
        <div class="tool-category"></div>
        <div class="tool-meta"></div>
      `;
      item.querySelector(".tool-name").textContent = tool.name;
      item.querySelector(".tool-category").textContent = tool.category;
      item.querySelector(".tool-meta").textContent = `dry-run: ${tool.dry_run} - ${tool.description}`;
      return item;
    }),
  );
}

function renderRuns() {
  const query = els.runSearch.value.trim().toLowerCase();
  const runs = state.runs.filter((run) => {
    const matchesQuery = !query || run.run_id.toLowerCase().includes(query);
    const matchesRisk = state.runRiskFilter === "all" || run.risk_level === state.runRiskFilter;
    return matchesQuery && matchesRisk;
  });
  if (runs.length === 0) {
    els.runList.innerHTML = '<div class="empty-state">No runs match the current search or risk filter.</div>';
    return;
  }
  els.runList.replaceChildren(
    ...runs.map((run) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `run-item${run.run_id === state.selectedRunId ? " selected" : ""}`;
      button.innerHTML = `
        <div class="run-id"></div>
        <div class="run-risk"></div>
        <div class="run-meta"></div>
      `;
      button.querySelector(".run-id").textContent = run.run_id;
      button.querySelector(".run-risk").textContent = `${run.status || "unknown"} / ${run.risk_level || "attention"}`;
      button.querySelector(".run-meta").textContent = new Date(run.updated_at).toLocaleString();
      button.addEventListener("click", () => selectRun(run.run_id));
      return button;
    }),
  );
}

function renderEmptyRuns() {
  state.selectedDetail = null;
  els.selectedRunTitle.textContent = "No runs yet";
  els.runState.textContent = "waiting";
  showSummary("Use the chat box or run agent start from a terminal to create the first run.");
  els.taskReviewList.innerHTML = '<div class="empty-state">Task Review appears after a run is selected.</div>';
  els.workflowHintList.innerHTML = '<div class="empty-state">Workflow Hints appear after a run is selected.</div>';
  els.failureSummaryList.innerHTML = '<div class="empty-state">Failure Summary appears after a run is selected.</div>';
  els.patchReviewList.innerHTML = '<div class="empty-state">Patch Review appears after a run is selected.</div>';
  els.failureRecoveryList.innerHTML = '<div class="empty-state">Failure Recovery appears after a run is selected.</div>';
  els.runReplayList.innerHTML = '<div class="empty-state">Run Replay appears after a run is selected.</div>';
  els.toolCallList.innerHTML = '<div class="empty-state">Trace appears after a run is selected.</div>';
  els.snapshotList.innerHTML = '<div class="empty-state">No snapshots recorded for this run.</div>';
}

function addActivityEvent(title, detail) {
  const item = document.createElement("article");
  item.className = "activity-item";
  item.innerHTML = `
    <div class="tool-name"></div>
    <div class="trace-meta"></div>
  `;
  item.querySelector(".tool-name").textContent = title;
  item.querySelector(".trace-meta").textContent = detail;
  els.activityLog.prepend(item);
  while (els.activityLog.children.length > 12) {
    els.activityLog.lastElementChild.remove();
  }
}

function showApprovalPanel(action, detail, onApprove, onDeny) {
  state.pendingApproval = { onApprove, onDeny };
  els.approvalAction.textContent = action;
  els.approvalDetail.textContent = detail;
  els.approvalPanel.classList.remove("hidden");
  addActivityEvent("Waiting for approval", action);
}

function hideApprovalPanel() {
  state.pendingApproval = null;
  els.approvalPanel.classList.add("hidden");
}

function showSummary(text) {
  state.openFilePath = null;
  els.fileEditor.classList.add("hidden");
  els.saveFileButton.classList.add("hidden");
  els.summary.classList.remove("hidden");
  els.summary.textContent = text;
}

function showFileEditor(payload) {
  state.openFilePath = payload.path;
  els.summary.classList.add("hidden");
  els.fileEditor.classList.remove("hidden");
  els.saveFileButton.classList.remove("hidden");
  els.fileEditor.value = payload.content || "";
}

async function selectRun(runId) {
  state.selectedRunId = runId;
  renderRuns();
  const detail = await loadJson(`/api/runs/${encodeURIComponent(runId)}`);
  state.selectedDetail = detail;
  els.selectedRunTitle.textContent = detail.run_id;
  showSummary(detail.summary || "(summary is empty)");
  const lastCall = detail.tool_calls[detail.tool_calls.length - 1];
  els.runState.textContent = lastCall?.data?.observation?.status || "loaded";
  renderTaskReview(detail.review);
  renderWorkflowHints(detail.workflow);
  renderFailureSummary(detail.failure);
  renderPatchReview(detail.patch_review);
  renderFailureRecovery(detail.recovery);
  renderSelectedRunLogs();
  renderSnapshots(detail.snapshots);
}

function renderSelectedRunLogs() {
  if (!state.selectedDetail) {
    renderRunReplay(null);
    renderToolCalls([]);
    return;
  }
  renderRunReplay(state.selectedDetail.replay);
  renderToolCalls(state.selectedDetail.tool_calls);
}

function renderTaskReview(review) {
  if (!review) {
    els.taskReviewList.innerHTML = '<div class="empty-state">No task review recorded.</div>';
    return;
  }
  const changedFiles = review.changed_files?.length ? review.changed_files.join(", ") : "none";
  const checks = review.manual_checks?.length ? review.manual_checks.join(" ") : "Review the summary and trace.";
  const rows = [
    ["Latest action", review.latest_action || "none"],
    ["Last observation", review.last_observation_summary || "No observation recorded."],
    ["Changed files", changedFiles],
    ["Snapshots", `${review.snapshot_count || 0}`],
    ["Manual checks", checks],
  ];
  els.taskReviewList.replaceChildren(
    ...rows.map(([label, value]) => {
      const item = document.createElement("article");
      item.className = "trace-item";
      item.innerHTML = `
        <div class="tool-name"></div>
        <div class="trace-meta"></div>
      `;
      item.querySelector(".tool-name").textContent = label;
      item.querySelector(".trace-meta").textContent = value;
      return item;
    }),
  );
}

function renderWorkflowHints(workflow) {
  if (!workflow) {
    els.workflowHintList.innerHTML = '<div class="empty-state">No workflow hints recorded.</div>';
    return;
  }
  const rows = [
    ["Mode", workflow.mode || "read-only"],
    ["Verification commands", workflow.verification_commands?.join("  |  ") || "none"],
    ["Review steps", workflow.review_steps?.join(" ") || "Review the summary and trace."],
  ];
  els.workflowHintList.replaceChildren(
    ...rows.map(([label, value]) => {
      const item = document.createElement("article");
      item.className = "trace-item";
      item.innerHTML = `
        <div class="tool-name"></div>
        <div class="trace-meta"></div>
      `;
      item.querySelector(".tool-name").textContent = label;
      item.querySelector(".trace-meta").textContent = value;
      return item;
    }),
  );
}

function renderFailureSummary(failure) {
  if (!failure) {
    els.failureSummaryList.innerHTML = '<div class="empty-state">No failure summary recorded.</div>';
    return;
  }
  const latest = failure.latest_failure;
  const latestText = latest
    ? `${latest.action || "unknown"} (${latest.error_code || latest.status || "error"}) - ${latest.summary || "No failure summary."}`
    : "none";
  const rows = [
    ["Status", failure.status || "clear"],
    ["Failure count", `${failure.failure_count || 0}`],
    ["Latest failure", latestText],
    ["Next checks", failure.next_checks?.join(" ") || "Review the summary and trace."],
  ];
  els.failureSummaryList.replaceChildren(
    ...rows.map(([label, value]) => {
      const item = document.createElement("article");
      item.className = "trace-item";
      item.innerHTML = `
        <div class="tool-name"></div>
        <div class="trace-meta"></div>
      `;
      item.querySelector(".tool-name").textContent = label;
      item.querySelector(".trace-meta").textContent = value;
      return item;
    }),
  );
}

function renderPatchReview(patchReview) {
  if (!patchReview) {
    els.patchReviewList.innerHTML = '<div class="empty-state">No patch review recorded.</div>';
    return;
  }
  const rows = [
    ["Risk", patchReview.risk_level || "low"],
    ["Summary", patchReview.summary || "No patch review summary."],
    ["Checks", patchReview.checks?.join(" ") || "Review the summary and trace."],
    ["Verification", patchReview.verification_commands?.join("  |  ") || "none"],
    ["Next action", patchReview.next_action || "No action suggested."],
  ];
  els.patchReviewList.replaceChildren(
    ...rows.map(([label, value]) => {
      const item = document.createElement("article");
      item.className = "trace-item";
      item.innerHTML = `
        <div class="tool-name"></div>
        <div class="trace-meta"></div>
      `;
      item.querySelector(".tool-name").textContent = label;
      item.querySelector(".trace-meta").textContent = value;
      return item;
    }),
  );
}

function renderFailureRecovery(recovery) {
  if (!recovery) {
    els.failureRecoveryList.innerHTML = '<div class="empty-state">No failure recovery recorded.</div>';
    return;
  }
  const latest = recovery.latest_failure;
  const latestText = latest
    ? `${latest.action || "unknown"} (${latest.error_code || latest.status || "error"}) - ${latest.summary || "No failure summary."}`
    : "none";
  const rows = [
    ["Status", recovery.status || "clear"],
    ["Rollback available", recovery.rollback_available ? "yes" : "no"],
    ["Summary", recovery.summary || "No recovery summary."],
    ["Latest failure", latestText],
    ["Steps", recovery.steps?.join(" ") || "No recovery action needed."],
    ["Checks", recovery.checks?.join(" ") || "Review the summary and trace."],
    ["Verification", recovery.verification_commands?.join("  |  ") || "none"],
    ["Next action", recovery.next_action || "No action suggested."],
  ];
  els.failureRecoveryList.replaceChildren(...rows.map(([label, value]) => traceItem(label, value)));
}

function renderRunReplay(replay) {
  if (!replay || !replay.steps?.length) {
    els.runReplayList.innerHTML = '<div class="empty-state">No replay steps recorded.</div>';
    return;
  }
  const steps = replay.steps.filter((step) =>
    matchesLogFilter({
      action: step.action,
      status: step.status,
      summary: step.summary,
      phase: step.phase,
      policy: step.policy_decision,
      terminal: step.terminal,
    }),
  );
  const countItem = document.createElement("article");
  countItem.className = "trace-item";
  countItem.innerHTML = `
    <div class="tool-name">Steps</div>
    <div class="trace-meta"></div>
  `;
  countItem.querySelector(".trace-meta").textContent = `${steps.length}/${replay.step_count || replay.steps.length}`;
  if (steps.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No replay steps match filters.";
    els.runReplayList.replaceChildren(countItem, empty);
    return;
  }
  els.runReplayList.replaceChildren(
    countItem,
    ...steps.map((step) => {
      const item = document.createElement("article");
      item.className = "trace-item";
      item.innerHTML = `
        <div class="tool-name"></div>
        <div class="trace-meta"></div>
        <div class="trace-meta"></div>
      `;
      item.querySelector(".tool-name").textContent = `${step.line_number}. ${step.action}`;
      item.querySelectorAll(".trace-meta")[0].textContent =
        `${step.phase} - ${step.status} - terminal: ${step.terminal}`;
      item.querySelectorAll(".trace-meta")[1].textContent =
        `${step.summary} ${step.policy_decision ? `policy: ${step.policy_decision}` : ""}`.trim();
      return item;
    }),
  );
}

function renderToolCalls(toolCalls) {
  const rows = toolCalls
    .map((call) => ({
      action: call.data?.action?.action?.name || "invalid",
      observation: call.data?.observation?.summary || call.error || "No summary.",
      phase: call.data?.trace?.phase || "action",
      policy: call.data?.trace?.policy_decision || "",
      status: call.data?.observation?.status || (call.valid ? "ok" : "invalid"),
      terminal: Boolean(call.data?.trace?.terminal),
      lineNumber: call.line_number,
    }))
    .filter((row) =>
      matchesLogFilter({
        action: row.action,
        status: row.status,
        summary: row.observation,
        phase: row.phase,
        policy: row.policy,
        terminal: row.terminal,
      }),
    );
  if (!toolCalls.length) {
    els.toolCallList.innerHTML = '<div class="empty-state">No tool calls recorded.</div>';
    return;
  }
  if (!rows.length) {
    els.toolCallList.innerHTML = '<div class="empty-state">No trace rows match filters.</div>';
    return;
  }
  els.toolCallList.replaceChildren(
    ...rows.map((row) => {
      const item = document.createElement("article");
      item.className = "trace-item";
      item.innerHTML = `
        <div class="tool-name"></div>
        <div class="trace-meta"></div>
        <div class="trace-meta"></div>
      `;
      item.querySelector(".tool-name").textContent = row.action;
      item.querySelectorAll(".trace-meta")[0].textContent = `line ${row.lineNumber} - ${row.status}`;
      item.querySelectorAll(".trace-meta")[1].textContent = row.observation;
      return item;
    }),
  );
}

function matchesLogFilter(row) {
  const terminal = state.logFilterTerminal;
  if (terminal === "terminal" && !row.terminal) {
    return false;
  }
  if (terminal === "non-terminal" && row.terminal) {
    return false;
  }

  const query = state.logFilterText.trim().toLowerCase();
  if (!query) {
    return true;
  }
  return [row.action, row.status, row.summary, row.phase, row.policy]
    .join(" ")
    .toLowerCase()
    .includes(query);
}

function renderSnapshots(snapshots) {
  if (!snapshots.length) {
    els.snapshotList.innerHTML = '<div class="empty-state">No snapshots for this run.</div>';
    return;
  }
  els.snapshotList.replaceChildren(
    ...snapshots.map((snapshot) => {
      const item = document.createElement("article");
      item.className = "trace-item";
      item.innerHTML = `
        <div class="tool-name"></div>
        <div class="trace-meta"></div>
        <div class="trace-meta"></div>
        <button class="diff-button" type="button">Show diff</button>
        <button class="restore-button" type="button">Restore</button>
      `;
      item.querySelector(".tool-name").textContent = snapshot.path;
      item.querySelectorAll(".trace-meta")[0].textContent = snapshot.snapshot_path;
      item.querySelectorAll(".trace-meta")[1].textContent = snapshot.restore_hint || "No restore hint.";
      item.querySelector(".diff-button").addEventListener("click", () => openDiff(snapshot.path, snapshot.snapshot_path));
      item.querySelector(".restore-button").addEventListener("click", () => restoreSnapshot(snapshot));
      return item;
    }),
  );
}

async function loadFiles(path) {
  try {
    const payload = await loadJson(`/api/files?path=${encodeURIComponent(path)}`);
    renderFiles(payload.entries, payload.path);
  } catch (error) {
    els.fileList.innerHTML = `<div class="empty-state">${error instanceof Error ? error.message : String(error)}</div>`;
  }
}

function renderFiles(entries, currentPath) {
  const parent = parentPath(currentPath);
  const rows = [];
  if (currentPath !== "." && parent) {
    rows.push(fileButton("..", parent, "dir"));
  }
  rows.push(...entries.map((entry) => fileButton(entry.name, entry.path, entry.kind)));
  els.fileList.replaceChildren(...rows);
}

function fileButton(name, path, kind) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "file-item";
  button.innerHTML = `
    <div class="run-id"></div>
    <div class="run-meta"></div>
  `;
  button.querySelector(".run-id").textContent = name;
  button.querySelector(".run-meta").textContent = `${kind} - ${path}`;
  button.addEventListener("click", () => (kind === "dir" ? loadFiles(path) : openFile(path)));
  return button;
}

async function openFile(path) {
  try {
    const payload = await loadJson(`/api/file?path=${encodeURIComponent(path)}`);
    els.selectedRunTitle.textContent = payload.path;
    els.runState.textContent = payload.truncated ? "truncated" : "file";
    showFileEditor(payload);
  } catch (error) {
    els.runState.textContent = "error";
    showSummary(error instanceof Error ? error.message : String(error));
  }
}

async function openDiff(path, snapshotPath) {
  try {
    const query = `path=${encodeURIComponent(path)}&snapshot=${encodeURIComponent(snapshotPath)}`;
    const payload = await loadJson(`/api/diff?${query}`);
    els.selectedRunTitle.textContent = `Diff: ${payload.path}`;
    els.runState.textContent = payload.truncated ? "truncated" : "diff";
    showSummary(payload.diff || "(no changes)");
  } catch (error) {
    els.runState.textContent = "error";
    showSummary(error instanceof Error ? error.message : String(error));
  }
}

async function saveOpenFile() {
  if (!state.openFilePath) {
    return;
  }
  const path = state.openFilePath;
  showApprovalPanel(
    "Save file",
    path,
    async () => {
      try {
        addActivityEvent("Saving file", path);
        const payload = await postJson("/api/file/save", {
          path,
          content: els.fileEditor.value,
        });
        addActivityEvent("File saved", payload.path);
        await loadFiles(".");
        const runs = await loadJson("/api/runs");
        state.runs = runs.runs;
        await selectRun(payload.run_id);
      } catch (error) {
        addActivityEvent("Save failed", error instanceof Error ? error.message : String(error));
        els.runState.textContent = "error";
        showSummary(error instanceof Error ? error.message : String(error));
      }
    },
    () => addActivityEvent("Save denied", path),
  );
}

async function restoreSnapshot(snapshot) {
  showApprovalPanel(
    "Restore snapshot",
    `${snapshot.path} from ${snapshot.snapshot_path}`,
    async () => {
      try {
        addActivityEvent("Restoring snapshot", snapshot.snapshot_path);
        const payload = await postJson("/api/snapshot/restore", {
          path: snapshot.path,
          snapshot_path: snapshot.snapshot_path,
        });
        els.selectedRunTitle.textContent = `Restored: ${payload.path}`;
        els.runState.textContent = payload.action;
        showSummary(`${payload.action}: ${payload.path}\nsnapshot: ${payload.snapshot_path}`);
        await loadFiles(".");
        addActivityEvent("Restore completed", payload.path);
      } catch (error) {
        addActivityEvent("Restore failed", error instanceof Error ? error.message : String(error));
        els.runState.textContent = "error";
        showSummary(error instanceof Error ? error.message : String(error));
      }
    },
    () => addActivityEvent("Restore denied", snapshot.path),
  );
}

function parentPath(path) {
  const parts = path.split("/").filter(Boolean);
  parts.pop();
  return parts.length ? parts.join("/") : ".";
}

async function sendChatTurn(message, { approveOnce = false } = {}) {
  if (!message) {
    els.messageInput.focus();
    return;
  }
  els.sendButton.disabled = true;
  els.runState.textContent = approveOnce ? "approved" : "running";
  showSummary(`${approveOnce ? "Submitting approved action" : "Submitting request"}...\n\n${message}`);
  addActivityEvent(approveOnce ? "Submitting approved action" : "Submitting request", message);
  addActivityEvent("Waiting for run engine", "Calling /api/chat/turn.");
  try {
    const turn = await postJson("/api/chat/turn", { session_id: state.sessionId, message, approve_once: approveOnce });
    addActivityEvent("Run finished", `run_id: ${turn.run_id}`);
    state.sessionId = turn.session_id;
    els.sessionChip.textContent = `session: ${turn.session_id}`;
    els.selectedRunTitle.textContent = turn.run_id;
    els.runState.textContent = turn.status;
    showSummary([
      `final: ${turn.final || "(empty)"}`,
      `status: ${turn.status}`,
      `completed: ${turn.completed}`,
      `terminal_reason: ${turn.terminal_reason}`,
      `last_action: ${turn.last_action}`,
      `last_observation_summary: ${turn.last_observation_summary}`,
      `summary: ${turn.summary_path}`,
    ].join("\n"));
    if (turn.approval_required) {
      showApprovalPanel(
        `Approve ${turn.requested_action}`,
        turn.last_observation_summary || "Action requires approval.",
        async () => {
          addActivityEvent("Approval granted", turn.requested_action);
          await sendChatTurn(message, { approveOnce: true });
        },
        () => addActivityEvent("Approval denied", turn.requested_action),
      );
      return;
    }
    els.messageInput.value = "";
    const runs = await loadJson("/api/runs");
    state.runs = runs.runs;
    await selectRun(turn.run_id);
    addActivityEvent(turn.completed ? "Run completed" : "Run stopped", turn.terminal_reason);
  } catch (error) {
    addActivityEvent("Run failed", error instanceof Error ? error.message : String(error));
    els.runState.textContent = "error";
    showSummary(error instanceof Error ? error.message : String(error));
  } finally {
    els.sendButton.disabled = false;
    els.messageInput.focus();
  }
}

async function submitChatTurn(event) {
  event.preventDefault();
  await sendChatTurn(els.messageInput.value.trim());
}

async function approvePendingAction() {
  const pending = state.pendingApproval;
  hideApprovalPanel();
  if (pending) {
    await pending.onApprove();
  }
}

function denyPendingAction() {
  const pending = state.pendingApproval;
  hideApprovalPanel();
  if (pending) {
    pending.onDeny();
  }
}

els.runSearch.addEventListener("input", renderRuns);
els.runRiskFilter.addEventListener("change", () => {
  state.runRiskFilter = els.runRiskFilter.value;
  renderRuns();
});
els.logFilterText.addEventListener("input", () => {
  state.logFilterText = els.logFilterText.value;
  renderSelectedRunLogs();
});
els.logFilterTerminal.addEventListener("change", () => {
  state.logFilterTerminal = els.logFilterTerminal.value;
  renderSelectedRunLogs();
});
els.chatForm.addEventListener("submit", submitChatTurn);
els.approveButton.addEventListener("click", approvePendingAction);
els.denyButton.addEventListener("click", denyPendingAction);
els.saveFileButton.addEventListener("click", saveOpenFile);
els.refreshButton.addEventListener("click", () => refreshWorkbench({ log: true }));

boot();
setInterval(() => refreshWorkbench(), 10000);
