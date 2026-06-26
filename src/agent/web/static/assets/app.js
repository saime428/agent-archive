const state = {
  runs: [],
  selectedRunId: null,
  sessionId: null,
  pendingApproval: null,
};

const els = {
  workspace: document.querySelector("#workspace-pill"),
  provider: document.querySelector("#provider-chip"),
  model: document.querySelector("#model-chip"),
  runList: document.querySelector("#run-list"),
  summary: document.querySelector("#summary-view"),
  selectedRunTitle: document.querySelector("#selected-run-title"),
  runState: document.querySelector("#run-state"),
  toolList: document.querySelector("#tool-list"),
  activityLog: document.querySelector("#activity-log"),
  approvalPanel: document.querySelector("#approval-panel"),
  approvalAction: document.querySelector("#approval-action"),
  approvalDetail: document.querySelector("#approval-detail"),
  approveButton: document.querySelector("#approve-button"),
  denyButton: document.querySelector("#deny-button"),
  toolCallList: document.querySelector("#tool-call-list"),
  snapshotList: document.querySelector("#snapshot-list"),
  fileList: document.querySelector("#file-list"),
  runSearch: document.querySelector("#run-search"),
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
    addActivityEvent("Workbench boot", "Loading health, tools, runs, and files.");
    const [health, tools, runs] = await Promise.all([
      loadJson("/api/health"),
      loadJson("/api/tools"),
      loadJson("/api/runs"),
    ]);
    renderHealth(health);
    renderTools(tools.tools);
    state.runs = runs.runs;
    renderRuns();
    if (state.runs.length > 0) {
      await selectRun(state.runs[0].run_id);
    } else {
      renderEmptyRuns();
    }
    await loadFiles(".");
    addActivityEvent("Workbench ready", "Local state loaded.");
  } catch (error) {
    addActivityEvent("Workbench error", error instanceof Error ? error.message : String(error));
    els.summary.textContent = error instanceof Error ? error.message : String(error);
  }
}

function renderHealth(health) {
  els.workspace.textContent = health.workspace;
  els.provider.textContent = `provider: ${health.provider}`;
  els.model.textContent = `model: ${health.model}`;
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
  const runs = query ? state.runs.filter((run) => run.run_id.toLowerCase().includes(query)) : state.runs;
  if (runs.length === 0) {
    els.runList.innerHTML = '<div class="empty-state">No matching runs.</div>';
    return;
  }
  els.runList.replaceChildren(
    ...runs.map((run) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `run-item${run.run_id === state.selectedRunId ? " selected" : ""}`;
      button.innerHTML = `
        <div class="run-id"></div>
        <div class="run-meta"></div>
      `;
      button.querySelector(".run-id").textContent = run.run_id;
      button.querySelector(".run-meta").textContent = new Date(run.updated_at).toLocaleString();
      button.addEventListener("click", () => selectRun(run.run_id));
      return button;
    }),
  );
}

function renderEmptyRuns() {
  els.selectedRunTitle.textContent = "No runs yet";
  els.runState.textContent = "waiting";
  els.summary.textContent = "Run `agent run` or `agent chat` to create durable logs, then refresh this page.";
  els.toolCallList.innerHTML = '<div class="empty-state">No tool calls yet.</div>';
  els.snapshotList.innerHTML = '<div class="empty-state">No snapshots yet.</div>';
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

async function selectRun(runId) {
  state.selectedRunId = runId;
  renderRuns();
  const detail = await loadJson(`/api/runs/${encodeURIComponent(runId)}`);
  els.selectedRunTitle.textContent = detail.run_id;
  els.summary.textContent = detail.summary || "(summary is empty)";
  const lastCall = detail.tool_calls[detail.tool_calls.length - 1];
  els.runState.textContent = lastCall?.data?.observation?.status || "loaded";
  renderToolCalls(detail.tool_calls);
  renderSnapshots(detail.snapshots);
}

function renderToolCalls(toolCalls) {
  if (!toolCalls.length) {
    els.toolCallList.innerHTML = '<div class="empty-state">No tool calls recorded.</div>';
    return;
  }
  els.toolCallList.replaceChildren(
    ...toolCalls.map((call) => {
      const action = call.data?.action?.action?.name || "invalid";
      const observation = call.data?.observation?.summary || call.error || "No summary.";
      const status = call.data?.observation?.status || (call.valid ? "ok" : "invalid");
      const item = document.createElement("article");
      item.className = "trace-item";
      item.innerHTML = `
        <div class="tool-name"></div>
        <div class="trace-meta"></div>
        <div class="trace-meta"></div>
      `;
      item.querySelector(".tool-name").textContent = action;
      item.querySelectorAll(".trace-meta")[0].textContent = `line ${call.line_number} - ${status}`;
      item.querySelectorAll(".trace-meta")[1].textContent = observation;
      return item;
    }),
  );
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
    els.summary.textContent = payload.content || "(empty file)";
  } catch (error) {
    els.runState.textContent = "error";
    els.summary.textContent = error instanceof Error ? error.message : String(error);
  }
}

async function openDiff(path, snapshotPath) {
  try {
    const query = `path=${encodeURIComponent(path)}&snapshot=${encodeURIComponent(snapshotPath)}`;
    const payload = await loadJson(`/api/diff?${query}`);
    els.selectedRunTitle.textContent = `Diff: ${payload.path}`;
    els.runState.textContent = payload.truncated ? "truncated" : "diff";
    els.summary.textContent = payload.diff || "(no changes)";
  } catch (error) {
    els.runState.textContent = "error";
    els.summary.textContent = error instanceof Error ? error.message : String(error);
  }
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
        els.summary.textContent = `${payload.action}: ${payload.path}\nsnapshot: ${payload.snapshot_path}`;
        await loadFiles(".");
        addActivityEvent("Restore completed", payload.path);
      } catch (error) {
        addActivityEvent("Restore failed", error instanceof Error ? error.message : String(error));
        els.runState.textContent = "error";
        els.summary.textContent = error instanceof Error ? error.message : String(error);
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
  els.summary.textContent = `${approveOnce ? "Submitting approved action" : "Submitting browser chat turn"}...\n\n${message}`;
  addActivityEvent(approveOnce ? "Submitting approved action" : "Submitting browser chat turn", message);
  addActivityEvent("Waiting for agent core", "Calling /api/chat/turn.");
  try {
    const turn = await postJson("/api/chat/turn", { session_id: state.sessionId, message, approve_once: approveOnce });
    addActivityEvent("Run response received", `run_id: ${turn.run_id}`);
    state.sessionId = turn.session_id;
    els.sessionChip.textContent = `session: ${turn.session_id}`;
    els.selectedRunTitle.textContent = turn.run_id;
    els.runState.textContent = turn.status;
    els.summary.textContent = [
      `final: ${turn.final || "(empty)"}`,
      `status: ${turn.status}`,
      `completed: ${turn.completed}`,
      `terminal_reason: ${turn.terminal_reason}`,
      `last_action: ${turn.last_action}`,
      `last_observation_summary: ${turn.last_observation_summary}`,
      `summary: ${turn.summary_path}`,
    ].join("\n");
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
    els.summary.textContent = error instanceof Error ? error.message : String(error);
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
els.chatForm.addEventListener("submit", submitChatTurn);
els.approveButton.addEventListener("click", approvePendingAction);
els.denyButton.addEventListener("click", denyPendingAction);

boot();
