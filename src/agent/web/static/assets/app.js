const state = {
  activeView: "chat",
  health: null,
  config: null,
  tools: [],
  runs: [],
  chats: [],
  selectedRunId: null,
  selectedDetail: null,
  selectedChat: null,
  sessionId: null,
  openFilePath: null,
  pendingApproval: null,
  activeSidePanel: "files",
  chatQuery: "",
  fileQuery: "",
  fileEntries: [],
  fileCurrentPath: ".",
  animateLatestRunId: null,
};

const els = {
  navButtons: [...document.querySelectorAll(".nav-button[data-view]")],
  settingsNavButtons: [...document.querySelectorAll("[data-settings-target]")],
  contextPanels: [...document.querySelectorAll(".context-panel")],
  views: [...document.querySelectorAll(".app-view")],
  workspace: document.querySelector("#workspace-pill"),
  provider: document.querySelector("#provider-chip"),
  model: document.querySelector("#model-chip"),
  apiKey: document.querySelector("#api-key-chip"),
  webSearch: document.querySelector("#web-search-chip"),
  computerRead: document.querySelector("#computer-read-chip"),
  sessionChip: document.querySelector("#session-chip"),
  providerNotice: document.querySelector("#provider-notice"),
  refreshButton: document.querySelector("#refresh-button"),
  backToChatButton: document.querySelector("#back-to-chat-button"),
  sideTabButtons: [...document.querySelectorAll(".side-tab")],
  sidePanels: [...document.querySelectorAll(".side-panel")],
  chatList: document.querySelector("#chat-list"),
  chatSearch: document.querySelector("#chat-search"),
  resourceChatList: document.querySelector("#resource-chat-list"),
  resourceChatMainList: document.querySelector("#resource-chat-main-list"),
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
  resourceSummaryList: document.querySelector("#resource-summary-list"),
  snapshotList: document.querySelector("#snapshot-list"),
  editorWorkspacePath: document.querySelector("#editor-workspace-path"),
  recentFileList: document.querySelector("#recent-file-list"),
  settingsForm: document.querySelector("#settings-form"),
  settingsProvider: document.querySelector("#settings-provider"),
  settingsModel: document.querySelector("#settings-model"),
  settingsSandbox: document.querySelector("#settings-sandbox"),
  settingsApproval: document.querySelector("#settings-approval"),
  settingsSkills: document.querySelector("#settings-skills"),
  settingsDryRun: document.querySelector("#settings-dry-run"),
  settingsWebSearch: document.querySelector("#settings-web-search"),
  settingsComputerRead: document.querySelector("#settings-computer-read"),
  settingsStatus: document.querySelector("#settings-status"),
  settingsKeyStatus: document.querySelector("#settings-key-status"),
  settingsToolList: document.querySelector("#settings-tool-list"),
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
  for (const button of els.settingsNavButtons) {
    button.addEventListener("click", () => scrollToSetting(button.dataset.settingsTarget));
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
  els.messageInput.addEventListener("keydown", handleMessageKeydown);
  els.approveButton.addEventListener("click", approvePendingAction);
  els.denyButton.addEventListener("click", denyPendingAction);
  els.saveFileButton.addEventListener("click", saveOpenFile);
  els.settingsForm.addEventListener("submit", saveSettings);
  els.settingsWebSearch.addEventListener("change", () => saveSettingsValues("联网搜索设置已保存。"));
  els.settingsComputerRead.addEventListener("change", () => saveSettingsValues("电脑文件只读设置已保存。"));
}

function handleMessageKeydown(event) {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) {
    return;
  }
  event.preventDefault();
  els.chatForm.requestSubmit();
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

function scrollToSetting(targetId) {
  activateView("settings");
  for (const button of els.settingsNavButtons) {
    button.classList.toggle("active", button.dataset.settingsTarget === targetId);
  }
  document.getElementById(targetId)?.scrollIntoView({ block: "center", behavior: "smooth" });
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
  const [health, config, tools, runs, chats] = await Promise.all([
    loadJson("/api/health"),
    loadJson("/api/config"),
    loadJson("/api/tools"),
    loadJson("/api/runs"),
    loadJson("/api/chats"),
  ]);
  state.health = health;
  state.config = config;
  state.tools = tools.tools || [];
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
  els.provider.textContent = `Codex: ${health.provider || "unknown"}`;
  els.model.textContent = health.model || "DeepSeek";
  els.apiKey.textContent = `Key: ${health.deepseek_api_key_present ? "已配置" : "缺失"}`;
  const webEnabled = Boolean(state.config?.config?.web_search_enabled);
  els.webSearch.textContent = `联网：${webEnabled ? "开" : "关"}`;
  els.webSearch.classList.toggle("active", webEnabled);
  const computerReadEnabled = Boolean(state.config?.config?.computer_read_enabled);
  els.computerRead.textContent = `电脑文件：${computerReadEnabled ? "开" : "关"}`;
  els.computerRead.classList.toggle("active", computerReadEnabled);
  els.providerNotice.textContent = health.provider_notice || "";
  els.providerNotice.className = `provider-notice ${health.deepseek_api_key_present ? "ok" : "warning"}`;
  if (els.editorWorkspacePath) {
    els.editorWorkspacePath.textContent = health.workspace || "workspace";
  }
  if (els.settingsKeyStatus) {
    els.settingsKeyStatus.textContent = `DeepSeek key: ${health.deepseek_api_key_present ? "已配置" : "缺失"} (${health.deepseek_api_key_env || "DEEPSEEK_API_KEY"})`;
  }
  renderRows(els.workspaceRiskList, [
    ["风险", health.workspace_risk?.risk_level || "low"],
    ["摘要", health.workspace_risk?.summary || "暂无工作区风险摘要。"],
  ]);
  renderRows(els.settingsReadinessList, [
    ["状态", health.settings_readiness?.status || "ready"],
    ["服务商", health.settings_readiness?.provider || health.provider || "unknown"],
    ["模型", health.settings_readiness?.model || health.model || "unknown"],
    ["DeepSeek key", health.deepseek_api_key_present ? "已配置" : "缺失"],
    ["联网搜索", webEnabled ? "开" : "关"],
    ["读取电脑文件", state.config?.config?.computer_read_enabled ? "开（只读）" : "关"],
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
  els.settingsWebSearch.checked = Boolean(config.web_search_enabled);
  els.settingsComputerRead.checked = Boolean(config.computer_read_enabled);
  const readiness = state.health?.settings_readiness || {};
  renderRows(els.settingsReadinessList, [
    ["状态", readiness.status || "ready"],
    ["服务商", readiness.provider || config.provider || "unknown"],
    ["模型", readiness.model || config.model || "unknown"],
    ["DeepSeek key", readiness.deepseek_api_key_present ? "已配置" : "缺失"],
    ["联网搜索", config.web_search_enabled ? "开" : "关"],
    ["读取电脑文件", config.computer_read_enabled ? "开（只读）" : "关"],
  ]);
  renderRows(
    els.settingsToolList,
    state.tools.map((tool) => [tool.name, `${tool.category} / dry-run: ${tool.dry_run}`]),
  );
}

function renderChats() {
  const filtered = state.chats.filter((chat) => {
    const haystack = `${chat.latest_user || ""} ${chat.latest_final || ""} ${chat.status || ""}`.toLowerCase();
    return !state.chatQuery || haystack.includes(state.chatQuery);
  });
  const items = filtered.map((chat) => chatButton(chat));
  replaceOrEmpty(els.chatList, items, "还没有聊天会话。");
  replaceOrEmpty(els.resourceChatList, state.chats.map((chat) => chatButton(chat)), "还没有聊天会话。");
  replaceOrEmpty(els.resourceChatMainList, state.chats.map((chat) => chatButton(chat)), "还没有聊天会话。");
  renderSideChat();
}

function chatButton(chat) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `list-item${chat.session_id === state.sessionId ? " selected" : ""}`;
  button.innerHTML = '<strong></strong><span></span><small></small>';
  button.querySelector("strong").textContent = chat.latest_user || "新聊天";
  button.querySelector("span").textContent = chat.latest_final || chat.status || "暂无回答。";
  button.querySelector("small").textContent = `${chat.turn_count || 0} 轮`;
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
  renderSideChat();
  activateView("chat");
}

function startNewChat() {
  state.sessionId = null;
  state.selectedChat = null;
  els.sessionChip.textContent = "new session";
  renderChats();
  renderChatThread([]);
  renderSideChat();
  els.messageInput.focus();
}

function renderChatThread(turns) {
  if (!turns.length) {
    els.chatThread.innerHTML = '<div class="empty-state">新聊天</div>';
    return;
  }
  const bubbles = [];
  for (const turn of turns) {
    bubbles.push(messageBubble("user", turn.user));
    const body = turn.final || turn.last_observation_summary || turn.status || "暂无响应。";
    const animateThinking = state.animateLatestRunId && state.animateLatestRunId === turn.run_id;
    bubbles.push(messageBubble("agent", friendlyChatText(body), friendlyTerminalReason(turn.terminal_reason), turn.thinking_text || "", {
      animateThinking,
      openThinking: animateThinking,
    }));
  }
  els.chatThread.replaceChildren(...bubbles);
  els.chatThread.scrollTop = els.chatThread.scrollHeight;
  state.animateLatestRunId = null;
}

function renderSideChat() {
  const chat = state.selectedChat;
  if (!chat) {
    replaceOrEmpty(els.sideChatList, [], "当前没有会话。");
    return;
  }
  renderRows(els.sideChatList, [
    ["Session", chat.session_id],
    ["Turns", `${chat.turn_count || 0}`],
    ["Updated", chat.updated_at ? new Date(chat.updated_at).toLocaleString() : ""],
  ]);
}

function messageBubble(role, body, meta = "", thinkingText = "", options = {}) {
  const article = document.createElement("article");
  article.className = `message-bubble ${role}`;
  article.innerHTML = '<div class="message-role"></div><div class="message-body"></div><div class="message-meta"></div>';
  article.querySelector(".message-role").textContent = role === "user" ? "你" : "Agent";
  article.querySelector(".message-body").textContent = body;
  article.querySelector(".message-meta").textContent = meta;
  if (role === "agent" && thinkingText) {
    const details = document.createElement("details");
    details.className = "thought-process";
    details.open = Boolean(options.openThinking);
    const summary = document.createElement("summary");
    summary.textContent = "思考过程";
    const bodyNode = document.createElement("div");
    bodyNode.className = "thinking-copy";
    renderThinkingText(bodyNode, thinkingText, { animate: Boolean(options.animateThinking) });
    details.append(summary, bodyNode);
    article.append(details);
  }
  return article;
}

function friendlyChatText(text) {
  const value = String(text || "");
  const messages = {
    "Action requires approval before execution.": "这个操作需要你先在右侧审查里批准。",
    "Action requires approval.": "这个操作需要你先批准。",
    "Approval required.": "需要审批。",
    "Web search is disabled. Enable it in Settings before searching the internet.": "联网搜索已关闭，请在设置里打开后再搜索网络。",
  };
  return messages[value] || value;
}

function friendlyTerminalReason(reason) {
  const value = String(reason || "");
  const messages = {
    "error:APPROVAL_REQUIRED": "需要审批",
    done: "完成",
    ask_user: "等待补充",
    pending: "运行中",
  };
  return messages[value] || value;
}

function renderThinkingText(container, text, { animate = false } = {}) {
  if (animate && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    renderThinkingTextTyping(container, text);
    return;
  }
  container.replaceChildren();
  const lines = String(text).split(/\r?\n/);
  let list = null;
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      list = null;
      continue;
    }
    if (trimmed.startsWith("- ")) {
      if (!list) {
        list = document.createElement("ul");
        container.append(list);
      }
      const item = document.createElement("li");
      appendInlineCode(item, trimmed.slice(2));
      list.append(item);
      continue;
    }
    list = null;
    const paragraph = document.createElement("p");
    appendInlineCode(paragraph, trimmed);
    container.append(paragraph);
  }
}

function renderThinkingTextTyping(container, text) {
  const value = String(text);
  container.replaceChildren();
  container.classList.add("typing");
  const target = document.createElement("div");
  target.className = "thinking-typewriter";
  container.append(target);
  let index = 0;
  const tick = () => {
    index += 1;
    target.textContent = value.slice(0, index);
    if (index < value.length) {
      window.setTimeout(tick, 12);
      return;
    }
    container.classList.remove("typing");
    renderThinkingText(container, value);
  };
  tick();
}

function appendInlineCode(parent, text) {
  const parts = String(text).split("`");
  parts.forEach((part, index) => {
    if (!part) {
      return;
    }
    const node = index % 2
      ? Object.assign(document.createElement("code"), { textContent: part })
      : document.createTextNode(part);
    parent.append(node);
  });
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
  appendPendingMessage(message, approveOnce ? "正在提交已批准的操作..." : "正在运行...");
  try {
    const turn = await postJson("/api/chat/turn", {
      session_id: state.sessionId,
      message,
      approve_once: approveOnce,
    });
    state.sessionId = turn.session_id;
    state.animateLatestRunId = turn.run_id;
    els.sessionChip.textContent = `session: ${turn.session_id}`;
    if (turn.approval_required) {
      showApprovalPanel(
        `审批 ${turn.requested_action}`,
        friendlyChatText(turn.last_observation_summary || "这个操作需要你先批准。"),
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
      els.runState.textContent = `已修复 ${turn.repair_count} 次`;
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
  state.animateLatestRunId = "__pending__";
  renderChatThread([...existing, {
    user: userMessage,
    run_id: "__pending__",
    final: status,
    terminal_reason: "pending",
    thinking_text: "我正在推进本轮请求：\n- 已收到你的输入。\n- 正在等待模型返回动作。\n- 工具执行结果会整理成可公开的过程。",
  }]);
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
  renderResultNotice("等待审批", "approval_required");
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
  replaceOrEmpty(els.runList, items, "还没有运行记录。");
  replaceOrEmpty(els.resourceRunList, state.runs.map((run) => runButton(run)), "还没有运行记录。");
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
  renderResources();
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
  renderEditorHome();
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
  replaceOrEmpty(els.fileList, items, "没有找到文件。");
  replaceOrEmpty(els.sideFileList, sideItems, "没有找到文件。");
  renderEditorHome();
}

function renderEditorHome() {
  const files = state.fileEntries
    .filter((entry) => entry.kind !== "dir")
    .slice(0, 8)
    .map((entry) => fileButton(entry.name, entry.path, entry.kind));
  replaceOrEmpty(els.recentFileList, files, "当前目录没有可打开的文件。");
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
    showSummary(error instanceof Error ? error.message : String(error), "打开失败");
  }
}

async function saveOpenFile() {
  if (!state.openFilePath) {
    return;
  }
  const path = state.openFilePath;
    showApprovalPanel("保存文件", path, async () => {
    const payload = await postJson("/api/file/save", { path, content: els.fileEditor.value });
    await refreshWorkbench();
    await loadFiles(".");
    await selectRun(payload.run_id);
    showSummary(`已保存 ${payload.path}`, "已保存");
  });
}

function showSummary(text, title = "摘要") {
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
  showSummary(payload.diff || "（没有变化）", `差异：${payload.path}`);
}

async function restoreSnapshot(snapshot) {
  showApprovalPanel("恢复快照", snapshot.path, async () => {
    const payload = await postJson("/api/snapshot/restore", {
      path: snapshot.path,
      snapshot_path: snapshot.snapshot_path,
    });
    await refreshWorkbench();
    showSummary(`${payload.action}: ${payload.path}`, "快照已恢复");
  });
}

function renderResources() {
  const memory = state.health?.memory_review;
  const snapshotCount = state.selectedDetail?.snapshots?.length || 0;
  renderRows(els.resourceSummaryList, [
    ["会话", `${state.chats.length}`],
    ["运行记录", `${state.runs.length}`],
    ["快照", `${snapshotCount}`],
    ["工作区风险", state.health?.workspace_risk?.risk_level || "low"],
  ]);
  const rows = [
    ["Pending candidates", `${memory?.pending_count || 0}`],
    ["Active entries", `${memory?.active_count || 0}`],
  ];
  renderRows(els.resourceMemoryList, rows);
}

async function saveSettings(event) {
  event.preventDefault();
  await saveSettingsValues("设置已保存。");
}

function buildSettingsPayload() {
  return {
    provider: els.settingsProvider.value,
    model: els.settingsModel.value.trim(),
    sandbox: els.settingsSandbox.value,
    approval: els.settingsApproval.value,
    dry_run: els.settingsDryRun.checked,
    web_search_enabled: els.settingsWebSearch.checked,
    computer_read_enabled: els.settingsComputerRead.checked,
    default_skills: els.settingsSkills.value.split(",").map((item) => item.trim()).filter(Boolean),
  };
}

async function saveSettingsValues(successText) {
  const payload = {
    ...buildSettingsPayload(),
  };
  try {
    els.settingsStatus.textContent = "正在保存设置...";
    state.config = await postJson("/api/config", payload);
    await refreshWorkbench();
    els.settingsStatus.textContent = successText || "设置已保存。";
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
        element.innerHTML = '<div class="empty-state">选择一条运行记录查看诊断。</div>';
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
    els.runReplayList.innerHTML = '<div class="empty-state">没有记录回放步骤。</div>';
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
    els.toolCallList.innerHTML = '<div class="empty-state">没有记录工具调用。</div>';
    return;
  }
  renderRows(
    els.toolCallList,
    toolCalls.map((call) => {
      const action = call.data?.action?.action?.name || "invalid";
      const summary = call.data?.observation?.summary || call.error || "暂无摘要。";
      return [`${call.line_number}. ${action}`, summary];
    }),
  );
}

function renderTerminal(detail) {
  if (!els.terminalOutput) {
    return;
  }
  if (!detail) {
    els.terminalOutput.textContent = "未选择运行。";
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
    els.snapshotList.innerHTML = '<div class="empty-state">这次运行没有快照。</div>';
    return;
  }
  const items = snapshots.map((snapshot) => {
    const item = document.createElement("article");
    item.className = "trace-item";
    item.innerHTML = '<strong></strong><span></span><div class="row-actions"><button type="button">查看差异</button><button type="button">恢复</button></div>';
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
  replaceOrEmpty(container, items, "没有记录数据。");
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
  if (/^[A-Za-z]:\\/.test(path) || path.includes("\\")) {
    const normalized = path.replace(/\\+$/, "");
    const index = normalized.lastIndexOf("\\");
    return index > 2 ? normalized.slice(0, index) : normalized;
  }
  const parts = path.split("/").filter(Boolean);
  parts.pop();
  return parts.length ? parts.join("/") : ".";
}

boot().catch((error) => {
  renderResultNotice(error instanceof Error ? error.message : String(error), "error");
});
