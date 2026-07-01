const state = {
  activeView: "chat",
  health: null,
  config: null,
  runs: [],
  chats: [],
  selectedRunId: null,
  selectedDetail: null,
  selectedChat: null,
  sessionId: null,
  openFilePath: null,
  pendingApproval: null,
  activeSidePanel: "chat",
  chatQuery: "",
  fileQuery: "",
  fileEntries: [],
  fileCurrentPath: ".",
};

const els = {
  navButtons: [...document.querySelectorAll(".nav-button[data-view]")],
  contextPanels: [...document.querySelectorAll(".context-panel")],
  views: [...document.querySelectorAll(".app-view")],
  workspace: document.querySelector("#workspace-pill"),
  provider: document.querySelector("#provider-chip"),
  model: document.querySelector("#model-chip"),
  apiKey: document.querySelector("#api-key-chip"),
  sessionChip: document.querySelector("#session-chip"),
  providerNotice: document.querySelector("#provider-notice"),
  refreshButton: document.querySelector("#refresh-button"),
  backToChatButton: document.querySelector("#back-to-chat-button"),
  sideTabButtons: [...document.querySelectorAll(".side-tab")],
  sidePanels: [...document.querySelectorAll(".side-panel")],
  chatList: document.querySelector("#chat-list"),
  chatSearch: document.querySelector("#chat-search"),
  resourceChatList: document.querySelector("#resource-chat-list"),
  chatThread: document.querySelector("#chat-thread"),
  chatForm: document.querySelector("#chat-form"),
  messageInput: document.querySelector("#message-input"),
  sendButton: document.querySelector("#send-button"),
  newChatButton: document.querySelector("#new-chat-button"),
  approvalPanel: document.querySelector("#approval-panel"),
  approvalAction: document.querySelector("#approval-action"),
  approvalDetail: document.querySelector("#approval-detail"),
  approveButton: document.querySelector("#approve-button"),
  denyButton: document.querySelector("#deny-button"),
  runList: document.querySelector("#run-list"),
  resourceRunList: document.querySelector("#resource-run-list"),
  sideChatList: document.querySelector("#side-chat-list"),
  selectedRunTitle: document.querySelector("#selected-run-title"),
  runState: document.querySelector("#run-state"),
  fileList: document.querySelector("#file-list"),
  sideFileList: document.querySelector("#side-file-list"),
  fileSearch: document.querySelector("#file-search"),
  selectedFileTitle: document.querySelector("#selected-file-title"),
  summary: document.querySelector("#summary-view"),
  fileEditor: document.querySelector("#file-editor"),
  saveFileButton: document.querySelector("#save-file-button"),
  resourceMemoryList: document.querySelector("#resource-memory-list"),
  snapshotList: document.querySelector("#snapshot-list"),
  settingsForm: document.querySelector("#settings-form"),
  settingsProvider: document.querySelector("#settings-provider"),
  settingsModel: document.querySelector("#settings-model"),
  settingsSandbox: document.querySelector("#settings-sandbox"),
  settingsApproval: document.querySelector("#settings-approval"),
  settingsSkills: document.querySelector("#settings-skills"),
  settingsDryRun: document.querySelector("#settings-dry-run"),
  settingsStatus: document.querySelector("#settings-status"),
  taskReviewList: document.querySelector("#task-review-list"),
  workflowHintList: document.querySelector("#workflow-hint-list"),
  failureSummaryList: document.querySelector("#failure-summary-list"),
  patchReviewList: document.querySelector("#patch-review-list"),
  failureRecoveryList: document.querySelector("#failure-recovery-list"),
  runReplayList: document.querySelector("#run-replay-list"),
  toolCallList: document.querySelector("#tool-call-list"),
  workspaceRiskList: document.querySelector("#workspace-risk-list"),
  settingsReadinessList: document.querySelector("#settings-readiness-list"),
  terminalOutput: document.querySelector("#terminal-output"),
};

async function loadJson(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(await response.text());
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
  bindEvents();
  activateView("chat");
  await refreshWorkbench({ selectInitial: true });
  await loadFiles(".");
}

function bindEvents() {
  for (const button of els.navButtons) {
    button.addEventListener("click", () => activateView(button.dataset.view));
  }
  for (const button of els.sideTabButtons) {
    button.addEventListener("click", () => activateSidePanel(button.dataset.sidePanel));
  }
  els.refreshButton.addEventListener("click", () => refreshWorkbench());
  els.backToChatButton.addEventListener("click", () => activateView("chat"));
  els.newChatButton.addEventListener("click", startNewChat);
  els.chatSearch.addEventListener("input", () => {
    state.chatQuery = els.chatSearch.value.trim().toLowerCase();
    renderChats();
  });
  els.fileSearch.addEventListener("input", () => {
    state.fileQuery = els.fileSearch.value.trim().toLowerCase();
    renderFileEntries();
  });
  els.chatForm.addEventListener("submit", submitChatTurn);
  els.approveButton.addEventListener("click", approvePendingAction);
  els.denyButton.addEventListener("click", denyPendingAction);
  els.saveFileButton.addEventListener("click", saveOpenFile);
  els.settingsForm.addEventListener("submit", saveSettings);
}

function activateView(view) {
  state.activeView = view || "chat";
  for (const button of els.navButtons) {
    button.classList.toggle("active", button.dataset.view === state.activeView);
  }
  for (const section of els.views) {
    section.classList.toggle("active", section.dataset.view === state.activeView);
  }
  for (const panel of els.contextPanels) {
    panel.classList.toggle("active", panel.dataset.view === state.activeView);
  }
}

function activateSidePanel(panel) {
  state.activeSidePanel = panel || "review";
  for (const button of els.sideTabButtons) {
    button.classList.toggle("active", button.dataset.sidePanel === state.activeSidePanel);
  }
  for (const section of els.sidePanels) {
    section.classList.toggle("active", section.dataset.sidePanel === state.activeSidePanel);
  }
}

async function refreshWorkbench({ selectInitial = false } = {}) {
  const [health, config, runs, chats] = await Promise.all([
    loadJson("/api/health"),
    loadJson("/api/config"),
    loadJson("/api/runs"),
    loadJson("/api/chats"),
  ]);
  state.health = health;
  state.config = config;
  state.runs = runs.runs || [];
  state.chats = chats.chats || [];
  renderHealth();
  renderSettings();
  renderChats();
  renderRuns();
  renderResources();
  if (selectInitial && state.chats.length && !state.sessionId) {
    await selectChat(state.chats[0].session_id);
  } else if (!state.selectedChat) {
    renderChatThread([]);
  }
  if ((selectInitial || !state.selectedRunId) && state.runs.length) {
    await selectRun(state.runs[0].run_id);
  } else if (!state.selectedDetail) {
    renderDiagnostics(null);
  }
}

function renderHealth() {
  const health = state.health || {};
  els.workspace.textContent = health.workspace || "workspace";
  els.provider.textContent = `provider: ${health.provider || "unknown"}`;
  els.model.textContent = `model: ${health.model || "unknown"}`;
  els.apiKey.textContent = `DeepSeek key: ${health.deepseek_api_key_present ? "present" : "missing"}`;
  els.providerNotice.textContent = health.provider_notice || "";
  els.providerNotice.className = `provider-notice ${health.deepseek_api_key_present ? "ok" : "warning"}`;
  renderRows(els.workspaceRiskList, [
    ["Risk", health.workspace_risk?.risk_level || "low"],
    ["Summary", health.workspace_risk?.summary || "No workspace risk summary."],
  ]);
  renderRows(els.settingsReadinessList, [
    ["Status", health.settings_readiness?.status || "ready"],
    ["Provider", health.settings_readiness?.provider || health.provider || "unknown"],
    ["Model", health.settings_readiness?.model || health.model || "unknown"],
    ["DeepSeek key", health.deepseek_api_key_present ? "present" : "missing"],
  ]);
}

function renderSettings() {
  const config = state.config?.config || {};
  els.settingsProvider.value = config.provider || "deepseek";
  els.settingsModel.value = config.model || "deepseek-v4-flash";
  els.settingsSandbox.value = config.sandbox || "workspace-write";
  els.settingsApproval.value = config.approval || "risky-confirm";
  els.settingsSkills.value = (config.default_skills || ["code-dev"]).join(", ");
  els.settingsDryRun.checked = Boolean(config.dry_run);
}

function renderChats() {
  const filtered = state.chats.filter((chat) => {
    const haystack = `${chat.latest_user || ""} ${chat.latest_final || ""} ${chat.status || ""}`.toLowerCase();
    return !state.chatQuery || haystack.includes(state.chatQuery);
  });
  const items = filtered.map((chat) => chatButton(chat));
  replaceOrEmpty(els.chatList, items, "No chat sessions yet.");
  replaceOrEmpty(els.resourceChatList, state.chats.map((chat) => chatButton(chat)), "No chat sessions yet.");
  replaceOrEmpty(els.sideChatList, state.chats.map((chat) => chatButton(chat)), "No chat sessions yet.");
}

function chatButton(chat) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `list-item${chat.session_id === state.sessionId ? " selected" : ""}`;
  button.innerHTML = '<strong></strong><span></span><small></small>';
  button.querySelector("strong").textContent = chat.latest_user || "New chat";
  button.querySelector("span").textContent = chat.latest_final || chat.status || "No answer yet.";
  button.querySelector("small").textContent = `${chat.turn_count || 0} turns`;
  button.addEventListener("click", () => selectChat(chat.session_id));
  return button;
}

async function selectChat(sessionId) {
  const payload = await loadJson(`/api/chats/${encodeURIComponent(sessionId)}`);
  state.sessionId = payload.session_id;
  state.selectedChat = payload;
  els.sessionChip.textContent = `session: ${payload.session_id}`;
  renderChats();
  renderChatThread(payload.turns || []);
  activateView("chat");
}

function startNewChat() {
  state.sessionId = null;
  state.selectedChat = null;
  els.sessionChip.textContent = "new session";
  renderChats();
  renderChatThread([]);
  els.messageInput.focus();
}

function renderChatThread(turns) {
  if (!turns.length) {
    els.chatThread.innerHTML = '<div class="empty-state">New chat</div>';
    return;
  }
  const bubbles = [];
  for (const turn of turns) {
    bubbles.push(messageBubble("user", turn.user));
    const body = turn.final || turn.last_observation_summary || turn.status || "No response.";
    bubbles.push(messageBubble("agent", body, turn.terminal_reason, turn.process || []));
  }
  els.chatThread.replaceChildren(...bubbles);
  els.chatThread.scrollTop = els.chatThread.scrollHeight;
}

function messageBubble(role, body, meta = "", process = []) {
  const article = document.createElement("article");
  article.className = `message-bubble ${role}`;
  article.innerHTML = '<div class="message-role"></div><div class="message-body"></div><div class="message-meta"></div>';
  article.querySelector(".message-role").textContent = role === "user" ? "You" : "Agent";
  article.querySelector(".message-body").textContent = body;
  article.querySelector(".message-meta").textContent = meta;
  if (role === "agent" && process.length) {
    const details = document.createElement("details");
    details.className = "thought-process";
    const summary = document.createElement("summary");
    summary.textContent = "思考过程";
    const list = document.createElement("ol");
    details.append(summary, list);
    for (const step of process) {
      const item = document.createElement("li");
      item.textContent = step;
      list.append(item);
    }
    article.append(details);
  }
  return article;
}

async function submitChatTurn(event) {
  event.preventDefault();
  await sendChatTurn(els.messageInput.value.trim());
}

async function sendChatTurn(message, { approveOnce = false } = {}) {
  if (!message) {
    els.messageInput.focus();
    return;
  }
  els.sendButton.disabled = true;
  appendPendingMessage(message, approveOnce ? "Submitting approved action..." : "Running...");
  try {
    const turn = await postJson("/api/chat/turn", {
      session_id: state.sessionId,
      message,
      approve_once: approveOnce,
    });
    state.sessionId = turn.session_id;
    els.sessionChip.textContent = `session: ${turn.session_id}`;
    if (turn.approval_required) {
      showApprovalPanel(
        `Approve ${turn.requested_action}`,
        turn.last_observation_summary || "Action requires approval.",
        async () => sendChatTurn(message, { approveOnce: true }),
      );
    } else {
      hideApprovalPanel();
      els.messageInput.value = "";
    }
    await refreshWorkbench();
    await selectChat(turn.session_id);
    await selectRun(turn.run_id);
    if (turn.has_repair_noise) {
      renderResultNotice(`Recovered after ${turn.repair_count} schema repair(s).`, turn.display_status);
    }
  } catch (error) {
    renderResultNotice(error instanceof Error ? error.message : String(error), "error");
  } finally {
    els.sendButton.disabled = false;
    els.messageInput.focus();
  }
}

function appendPendingMessage(userMessage, status) {
  const existing = state.selectedChat?.turns || [];
  renderChatThread([...existing, { user: userMessage, final: status, terminal_reason: "pending", process: ["正在提交本轮请求。"] }]);
}

function renderResultNotice(text, display_status) {
  const notice = document.createElement("article");
  notice.className = `result-notice ${display_status || "ok"}`;
  notice.textContent = text;
  els.chatThread.append(notice);
}

function showApprovalPanel(action, detail, onApprove) {
  state.pendingApproval = { onApprove };
  els.approvalAction.textContent = action;
  els.approvalDetail.textContent = detail;
  els.approvalPanel.classList.remove("hidden");
  renderResultNotice("Waiting for approval", "approval_required");
}

function hideApprovalPanel() {
  state.pendingApproval = null;
  els.approvalPanel.classList.add("hidden");
}

async function approvePendingAction() {
  const pending = state.pendingApproval;
  hideApprovalPanel();
  if (pending) {
    await pending.onApprove();
  }
}

function denyPendingAction() {
  hideApprovalPanel();
}

function renderRuns() {
  const items = state.runs.map((run) => runButton(run));
  replaceOrEmpty(els.runList, items, "No runs yet.");
  replaceOrEmpty(els.resourceRunList, state.runs.map((run) => runButton(run)), "No runs yet.");
}

function runButton(run) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `list-item${run.run_id === state.selectedRunId ? " selected" : ""}`;
  button.innerHTML = '<strong></strong><span></span><small></small>';
  button.querySelector("strong").textContent = run.run_id;
  button.querySelector("span").textContent = `${run.status || "unknown"} / ${run.risk_level || "low"}`;
  button.querySelector("small").textContent = new Date(run.updated_at).toLocaleString();
  button.addEventListener("click", () => selectRun(run.run_id));
  return button;
}

async function selectRun(runId) {
  const detail = await loadJson(`/api/runs/${encodeURIComponent(runId)}`);
  state.selectedRunId = detail.run_id;
  state.selectedDetail = detail;
  els.selectedRunTitle.textContent = detail.run_id;
  const lastCall = detail.tool_calls?.[detail.tool_calls.length - 1];
  els.runState.textContent = lastCall?.data?.observation?.status || "loaded";
  renderRuns();
  renderDiagnostics(detail);
  renderSnapshots(detail.snapshots || []);
}

async function loadFiles(path) {
  try {
    const payload = await loadJson(`/api/files?path=${encodeURIComponent(path)}`);
    renderFiles(payload.entries || [], payload.path || ".");
  } catch (error) {
    els.fileList.innerHTML = `<div class="empty-state">${error instanceof Error ? error.message : String(error)}</div>`;
  }
}

function renderFiles(entries, currentPath) {
  state.fileEntries = entries;
  state.fileCurrentPath = currentPath;
  renderFileEntries();
}

function renderFileEntries() {
  const items = [];
  const sideItems = [];
  const currentPath = state.fileCurrentPath;
  if (currentPath !== ".") {
    items.push(fileButton("..", parentPath(currentPath), "dir"));
    sideItems.push(fileButton("..", parentPath(currentPath), "dir"));
  }
  for (const entry of state.fileEntries) {
    const haystack = `${entry.name} ${entry.path}`.toLowerCase();
    if (state.fileQuery && !haystack.includes(state.fileQuery)) {
      continue;
    }
    items.push(fileButton(entry.name, entry.path, entry.kind));
    sideItems.push(fileButton(entry.name, entry.path, entry.kind));
  }
  replaceOrEmpty(els.fileList, items, "No files found.");
  replaceOrEmpty(els.sideFileList, sideItems, "No files found.");
}

function fileButton(name, path, kind) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "list-item";
  button.innerHTML = '<strong></strong><span></span>';
  button.querySelector("strong").textContent = name;
  button.querySelector("span").textContent = `${kind} - ${path}`;
  button.addEventListener("click", () => (kind === "dir" ? loadFiles(path) : openFile(path)));
  return button;
}

async function openFile(path) {
  try {
    const payload = await loadJson(`/api/file?path=${encodeURIComponent(path)}`);
    state.openFilePath = payload.path;
    els.selectedFileTitle.textContent = payload.path;
    els.summary.classList.add("hidden");
    els.fileEditor.classList.remove("hidden");
    els.saveFileButton.classList.remove("hidden");
    els.fileEditor.value = payload.content || "";
    activateView("editor");
  } catch (error) {
    showSummary(error instanceof Error ? error.message : String(error), "Open failed");
  }
}

async function saveOpenFile() {
  if (!state.openFilePath) {
    return;
  }
  const path = state.openFilePath;
  showApprovalPanel("Save file", path, async () => {
    const payload = await postJson("/api/file/save", { path, content: els.fileEditor.value });
    await refreshWorkbench();
    await loadFiles(".");
    await selectRun(payload.run_id);
    showSummary(`Saved ${payload.path}`, "Saved");
  });
}

function showSummary(text, title = "Summary") {
  els.selectedFileTitle.textContent = title;
  els.fileEditor.classList.add("hidden");
  els.saveFileButton.classList.add("hidden");
  els.summary.classList.remove("hidden");
  els.summary.textContent = text;
  activateView("editor");
}

async function openDiff(path, snapshotPath) {
  const query = `path=${encodeURIComponent(path)}&snapshot=${encodeURIComponent(snapshotPath)}`;
  const payload = await loadJson(`/api/diff?${query}`);
  showSummary(payload.diff || "(no changes)", `Diff: ${payload.path}`);
}

async function restoreSnapshot(snapshot) {
  showApprovalPanel("Restore snapshot", snapshot.path, async () => {
    const payload = await postJson("/api/snapshot/restore", {
      path: snapshot.path,
      snapshot_path: snapshot.snapshot_path,
    });
    await refreshWorkbench();
    showSummary(`${payload.action}: ${payload.path}`, "Snapshot restored");
  });
}

function renderResources() {
  const memory = state.health?.memory_review;
  const rows = [
    ["Pending candidates", `${memory?.pending_count || 0}`],
    ["Active entries", `${memory?.active_count || 0}`],
  ];
  renderRows(els.resourceMemoryList, rows);
}

async function saveSettings(event) {
  event.preventDefault();
  const payload = {
    provider: els.settingsProvider.value,
    model: els.settingsModel.value.trim(),
    sandbox: els.settingsSandbox.value,
    approval: els.settingsApproval.value,
    dry_run: els.settingsDryRun.checked,
    default_skills: els.settingsSkills.value.split(",").map((item) => item.trim()).filter(Boolean),
  };
  try {
    state.config = await postJson("/api/config", payload);
    els.settingsStatus.textContent = "Settings saved.";
    await refreshWorkbench();
  } catch (error) {
    els.settingsStatus.textContent = error instanceof Error ? error.message : String(error);
  }
}

function renderDiagnostics(detail) {
  if (!detail) {
    for (const element of [
      els.taskReviewList,
      els.workflowHintList,
      els.failureSummaryList,
      els.patchReviewList,
      els.failureRecoveryList,
      els.runReplayList,
      els.toolCallList,
    ]) {
      if (element) {
        element.innerHTML = '<div class="empty-state">Select a run to inspect diagnostics.</div>';
      }
    }
    renderSnapshots([]);
    renderTerminal(null);
    return;
  }
  renderRows(els.taskReviewList, objectRows(detail.review));
  renderRows(els.workflowHintList, objectRows(detail.workflow));
  renderRows(els.failureSummaryList, objectRows(detail.failure));
  renderRows(els.patchReviewList, objectRows(detail.patch_review));
  renderRows(els.failureRecoveryList, objectRows(detail.recovery));
  renderRunReplay(detail.replay);
  renderToolCalls(detail.tool_calls || []);
  renderTerminal(detail);
}

function renderRunReplay(replay) {
  if (!els.runReplayList) {
    return;
  }
  const steps = replay?.steps || [];
  if (!steps.length) {
    els.runReplayList.innerHTML = '<div class="empty-state">No replay steps recorded.</div>';
    return;
  }
  renderRows(
    els.runReplayList,
    steps.map((step) => [`${step.line_number}. ${step.action}`, `${step.status} - ${step.summary}`]),
  );
}

function renderToolCalls(toolCalls) {
  if (!els.toolCallList) {
    return;
  }
  if (!toolCalls.length) {
    els.toolCallList.innerHTML = '<div class="empty-state">No trace rows recorded.</div>';
    return;
  }
  renderRows(
    els.toolCallList,
    toolCalls.map((call) => {
      const action = call.data?.action?.action?.name || "invalid";
      const summary = call.data?.observation?.summary || call.error || "No summary.";
      return [`${call.line_number}. ${action}`, summary];
    }),
  );
}

function renderTerminal(detail) {
  if (!els.terminalOutput) {
    return;
  }
  if (!detail) {
    els.terminalOutput.textContent = "No run selected.";
    return;
  }
  const lines = [`$ run ${detail.run_id}`, ""];
  const steps = detail.replay?.steps || [];
  for (const step of steps) {
    lines.push(`${step.line_number}. ${step.action} [${step.status}]`);
    lines.push(`   ${step.summary}`);
  }
  if (detail.summary) {
    lines.push("", "summary:", detail.summary);
  }
  els.terminalOutput.textContent = lines.join("\n");
}

function renderSnapshots(snapshots) {
  if (!els.snapshotList) {
    return;
  }
  if (!snapshots.length) {
    els.snapshotList.innerHTML = '<div class="empty-state">No snapshots for this run.</div>';
    return;
  }
  const items = snapshots.map((snapshot) => {
    const item = document.createElement("article");
    item.className = "trace-item";
    item.innerHTML = '<strong></strong><span></span><div class="row-actions"><button type="button">Show diff</button><button type="button">Restore</button></div>';
    item.querySelector("strong").textContent = snapshot.path;
    item.querySelector("span").textContent = snapshot.snapshot_path;
    const buttons = item.querySelectorAll("button");
    buttons[0].addEventListener("click", () => openDiff(snapshot.path, snapshot.snapshot_path));
    buttons[1].addEventListener("click", () => restoreSnapshot(snapshot));
    return item;
  });
  els.snapshotList.replaceChildren(...items);
}

function objectRows(value) {
  if (!value || typeof value !== "object") {
    return [];
  }
  return Object.entries(value)
    .filter(([, item]) => item !== null && item !== undefined && typeof item !== "object")
    .map(([key, item]) => [key, String(item)]);
}

function renderRows(container, rows) {
  if (!container) {
    return;
  }
  const items = rows
    .filter(([, value]) => value)
    .map(([label, value]) => {
      const item = document.createElement("article");
      item.className = "trace-item";
      item.innerHTML = '<strong></strong><span></span>';
      item.querySelector("strong").textContent = label;
      item.querySelector("span").textContent = value;
      return item;
    });
  replaceOrEmpty(container, items, "No data recorded.");
}

function replaceOrEmpty(container, items, emptyText) {
  if (!container) {
    return;
  }
  if (!items.length) {
    container.innerHTML = `<div class="empty-state">${emptyText}</div>`;
    return;
  }
  container.replaceChildren(...items);
}

function parentPath(path) {
  const parts = path.split("/").filter(Boolean);
  parts.pop();
  return parts.length ? parts.join("/") : ".";
}

boot().catch((error) => {
  renderResultNotice(error instanceof Error ? error.message : String(error), "error");
});
