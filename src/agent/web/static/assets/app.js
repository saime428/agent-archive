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
  openChatIds: [],
  openFilePath: null,
  pendingApproval: null,
  activeSidePanel: "files",
  chatQuery: "",
  fileQuery: "",
  fileEntries: [],
  fileCurrentPath: ".",
  animateLatestRunId: null,
  liveTurn: null,
  liveEvents: [],
  activeJobId: null,
  eventSource: null,
  openChatMenuId: null,
  resourcePages: { chats: 0, runs: 0, snapshots: 0 },
};

const LEGACY_CHAT_TURN_ENDPOINT = "/api/chat/turn";

const els = {
  navButtons: [...document.querySelectorAll(".nav-button[data-view]")],
  settingsNavButtons: [...document.querySelectorAll("[data-settings-target]")],
  contextPanels: [...document.querySelectorAll(".context-panel")],
  views: [...document.querySelectorAll(".app-view")],
  workspace: document.querySelector("#workspace-pill"),
  shell: document.querySelector(".apix-shell"),
  leftResizer: document.querySelector("#left-resizer"),
  rightResizer: document.querySelector("#right-resizer"),
  provider: document.querySelector("#provider-chip"),
  model: document.querySelector("#model-chip"),
  apiKey: document.querySelector("#api-key-chip"),
  webSearch: document.querySelector("#web-search-chip"),
  computerRead: document.querySelector("#computer-read-chip"),
  modeChip: document.querySelector("#mode-chip"),
  sandboxChip: document.querySelector("#sandbox-chip"),
  sessionChip: document.querySelector("#session-chip"),
  providerNotice: document.querySelector("#provider-notice"),
  refreshButton: document.querySelector("#refresh-button"),
  themeToggle: document.querySelector("#theme-toggle"),
  conversationTabs: document.querySelector("#conversation-tabs"),
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
  resourcePanels: [...document.querySelectorAll("[data-resource-panel]")],
  resourceDetailModal: document.querySelector("#resource-detail-modal"),
  resourceDetailTitle: document.querySelector("#resource-detail-title"),
  resourceDetailBody: document.querySelector("#resource-detail-body"),
  resourceDetailClose: document.querySelector("#resource-detail-close"),
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
  const text = await response.text();
  let result = {};
  try {
    result = text ? JSON.parse(text) : {};
  } catch {
    result = { error: text };
  }
  if (!response.ok) {
    const error = new Error(result.error || `${path} failed`);
    error.status = response.status;
    throw error;
  }
  return result;
}

async function boot() {
  applyStoredTheme();
  bindEvents();
  initColumnResize();
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
  els.themeToggle?.addEventListener("click", toggleTheme);
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
  els.messageInput.addEventListener("input", autoResizeMessageInput);
  els.approveButton.addEventListener("click", approvePendingAction);
  els.denyButton.addEventListener("click", denyPendingAction);
  els.saveFileButton.addEventListener("click", saveOpenFile);
  els.settingsForm.addEventListener("submit", saveSettings);
  els.settingsWebSearch.addEventListener("change", () => saveSettingsValues("联网搜索设置已保存。"));
  els.settingsComputerRead.addEventListener("change", () => saveSettingsValues("电脑文件只读设置已保存。"));
  document.addEventListener("click", closeChatMenus);
  for (const panel of els.resourcePanels) {
    panel.addEventListener("click", () => openResourceDetail(panel.dataset.resourcePanel));
    panel.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") {
        return;
      }
      event.preventDefault();
      openResourceDetail(panel.dataset.resourcePanel);
    });
  }
  els.resourceDetailClose?.addEventListener("click", closeResourceDetail);
  els.resourceDetailModal?.addEventListener("click", (event) => {
    if (event.target === els.resourceDetailModal) {
      closeResourceDetail();
    }
  });
}

function handleMessageKeydown(event) {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) {
    return;
  }
  event.preventDefault();
  els.chatForm.requestSubmit();
}

function autoResizeMessageInput() {
  if (!els.messageInput) {
    return;
  }
  els.messageInput.style.height = "auto";
  els.messageInput.style.height = `${Math.min(180, els.messageInput.scrollHeight)}px`;
}

function applyStoredTheme() {
  const theme = localStorage.getItem("agent-theme");
  if (theme === "dark" || theme === "light") {
    document.documentElement.dataset.theme = theme;
  }
  updateThemeButton();
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("agent-theme", next);
  updateThemeButton();
}

function updateThemeButton() {
  if (!els.themeToggle) {
    return;
  }
  const dark = document.documentElement.dataset.theme === "dark";
  els.themeToggle.textContent = dark ? "☀" : "☾";
  els.themeToggle.setAttribute("aria-label", dark ? "切换到浅色主题" : "切换到深色主题");
}

function initColumnResize() {
  const left = localStorage.getItem("agent-left-column");
  const right = localStorage.getItem("agent-right-column");
  if (left) {
    document.documentElement.style.setProperty("--left-column", left);
  }
  if (right) {
    document.documentElement.style.setProperty("--right-column", right);
  }
  bindColumnResize(els.leftResizer, "left");
  bindColumnResize(els.rightResizer, "right");
}

function bindColumnResize(handle, side) {
  if (!handle || !els.shell) {
    return;
  }
  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    document.body.classList.add("resizing-columns");
    const rect = els.shell.getBoundingClientRect();
    const move = (moveEvent) => {
      const raw = side === "left" ? moveEvent.clientX - rect.left : rect.right - moveEvent.clientX;
      const width = Math.round(Math.min(620, Math.max(240, raw)));
      const name = side === "left" ? "--left-column" : "--right-column";
      document.documentElement.style.setProperty(name, `${width}px`);
      localStorage.setItem(side === "left" ? "agent-left-column" : "agent-right-column", `${width}px`);
    };
    const stop = () => {
      document.body.classList.remove("resizing-columns");
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", stop);
      handle.removeEventListener("pointercancel", stop);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);
  });
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
  state.openChatIds = state.openChatIds.filter((id) => state.chats.some((chat) => chat.session_id === id));
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
  const mode = health.mode || "guided";
  els.modeChip.textContent = `模式：${mode}`;
  els.modeChip.classList.toggle("active", mode !== "guided");
  const sandbox = health.sandbox || state.config?.config?.sandbox || "workspace-write";
  els.sandboxChip.textContent = `沙箱：${sandbox}`;
  els.sandboxChip.classList.toggle("active", sandbox !== "workspace-write");
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
  renderPagedList(els.resourceChatMainList, state.chats, "chats", chatPreviewItem, "还没有聊天会话。", 4);
  renderConversationTabs();
  renderSideChat();
}

function chatPreviewItem(chat) {
  return resourcePreviewItem(
    chat.title || chat.latest_user || "新聊天",
    chat.latest_final || chat.status || "暂无回答。",
    `${chat.turn_count || 0} 轮`,
  );
}

function chatButton(chat) {
  const item = document.createElement("article");
  item.className = `list-item chat-row${chat.session_id === state.sessionId ? " selected" : ""}`;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "chat-main-button";
  button.innerHTML = '<strong class="chat-title"></strong><span></span><small></small>';
  button.querySelector("strong").textContent = chat.title || chat.latest_user || "新聊天";
  button.querySelector("span").textContent = chat.latest_final || chat.status || "暂无回答。";
  button.querySelector("small").textContent = `${chat.turn_count || 0} 轮`;
  button.addEventListener("click", () => selectChat(chat.session_id));
  const menuButton = document.createElement("button");
  menuButton.type = "button";
  menuButton.className = "chat-menu-button";
  menuButton.textContent = "⋯";
  menuButton.setAttribute("aria-label", "会话菜单");
  menuButton.addEventListener("click", (event) => {
    event.stopPropagation();
    state.openChatMenuId = state.openChatMenuId === chat.session_id ? null : chat.session_id;
    renderChats();
  });
  item.append(button, menuButton);
  if (state.openChatMenuId === chat.session_id) {
    item.append(chatMenu(chat));
  }
  return item;
}

function chatMenu(chat) {
  const menu = document.createElement("div");
  menu.className = "chat-menu";
  const rename = document.createElement("button");
  rename.type = "button";
  rename.textContent = "重命名";
  rename.addEventListener("click", (event) => {
    event.stopPropagation();
    renameChat(chat);
  });
  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = "删除";
  remove.addEventListener("click", (event) => {
    event.stopPropagation();
    deleteChat(chat.session_id);
  });
  menu.append(rename, remove);
  return menu;
}

function closeChatMenus() {
  if (!state.openChatMenuId) {
    return;
  }
  state.openChatMenuId = null;
  renderChats();
}

async function renameChat(chat) {
  const title = globalThis.prompt("重命名会话", chat.title || chat.latest_user || "");
  if (!title || !title.trim()) {
    return;
  }
  try {
    await postJson("/api/chat/rename", { session_id: chat.session_id, title: title.trim() });
    state.openChatMenuId = null;
    await refreshWorkbench();
    if (state.sessionId === chat.session_id) {
      await selectChat(chat.session_id);
    }
  } catch (error) {
    showActionError("重命名失败", error);
  }
}

async function deleteChat(sessionId) {
  if (!globalThis.confirm("删除这个会话？此操作不可恢复。")) {
    return;
  }
  try {
    await postJson("/api/chat/delete", { session_id: sessionId });
    state.openChatMenuId = null;
    state.openChatIds = state.openChatIds.filter((id) => id !== sessionId);
    if (state.sessionId === sessionId) {
      state.sessionId = null;
      state.selectedChat = null;
    }
    await refreshWorkbench({ selectInitial: true });
  } catch (error) {
    showActionError("删除失败", error);
  }
}

function showActionError(prefix, error) {
  globalThis.alert(`${prefix}: ${backendErrorMessage(error)}`);
}

function backendErrorMessage(error) {
  const message = error instanceof Error ? error.message : String(error);
  if (error?.status === 404) {
    return `${message}。当前页面连到的后端不是最新进程，请关闭旧 8765 页面，重新用 start-agent.cmd 打开它显示的新地址。`;
  }
  return message;
}

async function selectChat(sessionId) {
  const payload = await loadJson(`/api/chats/${encodeURIComponent(sessionId)}`);
  state.sessionId = payload.session_id;
  state.selectedChat = payload;
  rememberOpenChat(payload.session_id);
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
  activateView("chat");
  els.messageInput.focus();
}

function rememberOpenChat(sessionId) {
  if (!sessionId || state.openChatIds.includes(sessionId)) {
    return;
  }
  state.openChatIds.push(sessionId);
}

function renderConversationTabs() {
  if (!els.conversationTabs) {
    return;
  }
  const tabs = [];
  if (!state.sessionId) {
    tabs.push(conversationTab({ title: "新聊天", session_id: null }, true));
  }
  for (const sessionId of state.openChatIds) {
    const chat = state.chats.find((item) => item.session_id === sessionId);
    if (!chat) {
      continue;
    }
    tabs.push(conversationTab(chat, chat.session_id === state.sessionId));
  }
  const newButton = document.createElement("button");
  newButton.type = "button";
  newButton.className = "conversation-tab add-tab";
  newButton.textContent = "+";
  newButton.setAttribute("aria-label", "新建聊天标签");
  newButton.addEventListener("click", startNewChat);
  tabs.push(newButton);
  els.conversationTabs.replaceChildren(...tabs);
}

function conversationTab(chat, active) {
  const tab = document.createElement("div");
  tab.className = `conversation-tab${active ? " active" : ""}`;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "tab-title";
  button.textContent = chat.title || chat.latest_user || "新聊天";
  if (chat.session_id) {
    button.addEventListener("click", () => selectChat(chat.session_id));
    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "tab-close";
    closeButton.textContent = "×";
    closeButton.setAttribute("aria-label", `关闭 ${button.textContent}`);
    closeButton.addEventListener("click", (event) => {
      event.stopPropagation();
      closeConversationTab(chat.session_id);
    });
    tab.append(button, closeButton);
  } else {
    button.addEventListener("click", startNewChat);
    tab.append(button);
  }
  return tab;
}

function closeConversationTab(sessionId) {
  const wasActive = sessionId === state.sessionId;
  state.openChatIds = state.openChatIds.filter((id) => id !== sessionId);
  if (!wasActive) {
    renderConversationTabs();
    return;
  }
  const nextSessionId = state.openChatIds.at(-1);
  if (nextSessionId) {
    selectChat(nextSessionId);
    return;
  }
  startNewChat();
}

function renderChatThread(turns) {
  const visibleTurns = [...turns];
  if (state.liveTurn && (!state.liveTurn.session_id || state.liveTurn.session_id === state.sessionId)) {
    visibleTurns.push(state.liveTurn);
  }
  if (!visibleTurns.length) {
    els.chatThread.replaceChildren(chatEmptyState());
    return;
  }
  const bubbles = [];
  for (const turn of visibleTurns) {
    bubbles.push(messageBubble("user", turn.user));
    const body = turn.final || turn.last_observation_summary || turn.status || "暂无响应。";
    const isLiveTurn = state.liveTurn && turn === state.liveTurn;
    const animateThinking = state.animateLatestRunId && state.animateLatestRunId === turn.run_id;
    bubbles.push(messageBubble("agent", friendlyChatText(body), friendlyTerminalReason(turn.terminal_reason), turn.thinking_text || "", {
      animateThinking,
      openThinking: animateThinking || isLiveTurn,
      events: turn.events || [],
      jobId: turn.job_id,
      loading: isLiveTurn && !["等待审批。"].includes(body) && !(turn.events || []).some((event) => ["final", "error"].includes(event.event)),
    }));
  }
  els.chatThread.replaceChildren(...bubbles);
  els.chatThread.scrollTop = els.chatThread.scrollHeight;
  state.animateLatestRunId = null;
}

function chatEmptyState() {
  const empty = document.createElement("section");
  empty.className = "empty-chat-state";
  empty.innerHTML = '<div class="empty-mark" aria-hidden="true">A</div><strong>新聊天</strong><span>把任务交给本地 Agent。</span>';
  return empty;
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
  if (options.loading) {
    renderMessageSkeleton(article.querySelector(".message-body"));
  } else {
    renderMessageBody(article.querySelector(".message-body"), body);
  }
  article.querySelector(".message-meta").textContent = meta;
  if (role === "agent" && (thinkingText || options.events?.length)) {
    const details = document.createElement("details");
    details.className = "thought-process";
    details.open = Boolean(options.openThinking);
    const summary = document.createElement("summary");
    summary.textContent = processSummary(options.events || []);
    const bodyNode = document.createElement("div");
    bodyNode.className = "thinking-copy";
    if (options.events?.length) {
      renderProcessCards(bodyNode, options.events, { jobId: options.jobId });
    } else {
      renderThinkingText(bodyNode, thinkingText, { animate: Boolean(options.animateThinking) });
    }
    details.append(summary, bodyNode);
    article.append(details);
  }
  return article;
}

function renderMessageSkeleton(container) {
  container.replaceChildren();
  const shell = document.createElement("div");
  shell.className = "message-skeleton";
  shell.append(document.createElement("span"), document.createElement("span"), document.createElement("span"));
  container.append(shell);
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
      appendInlineMarkdown(item, trimmed.slice(2));
      list.append(item);
      continue;
    }
    list = null;
    const paragraph = document.createElement("p");
    appendInlineMarkdown(paragraph, trimmed);
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

function renderProcessCards(container, events, { jobId } = {}) {
  container.replaceChildren();
  const visible = events.filter((event) => !["model_stream_chunk"].includes(event.event));
  for (const event of visible) {
    const card = document.createElement("article");
    card.className = `process-step-card ${processStatus(event)}`;
    const title = document.createElement("strong");
    title.textContent = processTitle(event);
    const detail = document.createElement("span");
    detail.textContent = processDetail(event);
    card.append(title, detail);
    if (event.event === "approval_required" && jobId) {
      const previewText = approvalPreview(event.args);
      if (previewText) {
        const preview = document.createElement("pre");
        preview.className = "approval-preview";
        preview.textContent = previewText;
        card.append(preview);
      }
      const actions = document.createElement("div");
      actions.className = "process-approval-actions";
      const resolved = events.some(
        (item) =>
          item.action_index === event.action_index &&
          ["approval_granted", "approval_denied"].includes(item.event),
      );
      const approveButton = document.createElement("button");
      approveButton.type = "button";
      approveButton.textContent = "批准";
      approveButton.disabled = resolved;
      approveButton.addEventListener("click", () => submitApproval(jobId, true, approveButton));
      const denyButton = document.createElement("button");
      denyButton.type = "button";
      denyButton.textContent = "拒绝";
      denyButton.disabled = resolved;
      denyButton.addEventListener("click", () => submitApproval(jobId, false, denyButton));
      actions.append(approveButton, denyButton);
      card.append(actions);
    }
    container.append(card);
  }
}

function approvalPreview(args) {
  if (!args || typeof args !== "object") {
    return "";
  }
  if (Array.isArray(args.argv)) {
    return args.argv.join(" ");
  }
  if (typeof args.patch === "string") {
    return args.patch.slice(0, 1200);
  }
  if (typeof args.content === "string") {
    const path = args.path ? `${args.path}\n` : "";
    return `${path}${args.content.slice(0, 1200)}`;
  }
  return actionTarget(args);
}

function processStatus(event) {
  if (event.event === "error" || event.status === "error" || event.event === "approval_denied") {
    return "error";
  }
  if (["final", "observation", "approval_granted"].includes(event.event)) {
    return "done";
  }
  if (event.event === "approval_required") {
    return "waiting";
  }
  return "running";
}

function processTitle(event) {
  const labels = {
    chat_started: "开始本轮任务",
    model_call_start: "调用模型",
    model_stream_start: "接收模型输出",
    action_parsed: `计划执行 ${actionLabel(event.action)}`,
    tool_start: `执行 ${actionLabel(event.action)}`,
    approval_required: `等待审批 ${actionLabel(event.action)}`,
    approval_granted: "审批通过",
    approval_denied: "审批拒绝",
    observation: `工具返回 ${actionLabel(event.action)}`,
    final: "整理最终回答",
    error: "运行出错",
  };
  return labels[event.event] || event.event || "运行事件";
}

function processDetail(event) {
  const elapsed = formatElapsed(event.elapsed_ms);
  if (event.event === "final") {
    const status = event.terminal_reason ? `状态：${friendlyTerminalReason(event.terminal_reason)}` : "已完成。";
    return elapsed ? `${status} · ${elapsed}` : status;
  }
  if (event.summary) {
    return elapsed ? `${event.summary} · ${elapsed}` : event.summary;
  }
  if (event.reason) {
    return elapsed ? `${event.reason} · ${elapsed}` : event.reason;
  }
  if (event.message) {
    return elapsed ? `${event.message} · ${elapsed}` : event.message;
  }
  const target = actionTarget(event.args);
  const detail = target ? `目标：${target}` : "等待下一步真实运行事件。";
  return elapsed ? `${detail} · ${elapsed}` : detail;
}

function processSummary(events) {
  const final = events.find((event) => event.event === "final");
  if (!final) {
    return "执行过程";
  }
  const steps = events.filter((event) => ["action_parsed", "tool_start", "observation", "approval_required"].includes(event.event)).length;
  const elapsed = formatElapsed(final.elapsed_ms);
  return elapsed ? `执行过程 · ${elapsed} · ${steps} 步` : `执行过程 · ${steps} 步`;
}

function formatElapsed(ms) {
  if (typeof ms !== "number") {
    return "";
  }
  if (ms < 1000) {
    return `${ms}ms`;
  }
  return `${(ms / 1000).toFixed(1)}s`;
}

function actionLabel(action) {
  const labels = {
    list_dir: "列目录",
    read_file: "读文件",
    search_files: "搜索文件",
    web_search: "联网搜索",
    write_file: "写文件",
    apply_patch: "应用补丁",
    run_command: "运行命令",
    git_status: "查看 Git 状态",
    git_diff: "查看 Git 差异",
    done: "完成",
    ask_user: "询问用户",
  };
  return labels[action] || action || "";
}

function actionTarget(args) {
  if (!args || typeof args !== "object") {
    return "";
  }
  const value = args.path || args.query || (Array.isArray(args.argv) ? args.argv.join(" ") : "");
  return String(value || "").slice(0, 120);
}

function renderMessageBody(container, text) {
  container.replaceChildren();
  const lines = String(text || "").split(/\r?\n/);
  let list = null;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();
    if (!trimmed) {
      list = null;
      continue;
    }
    if (trimmed.startsWith("```")) {
      const language = trimmed.slice(3).trim();
      const codeLines = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      renderCodeBlock(container, codeLines.join("\n"), language);
      list = null;
      continue;
    }
    if (isMarkdownTable(lines, index)) {
      const tableLines = [];
      while (index < lines.length && lines[index].includes("|")) {
        tableLines.push(lines[index]);
        index += 1;
      }
      index -= 1;
      renderMarkdownTable(container, tableLines);
      list = null;
      continue;
    }
    const bullet = trimmed.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      if (!list || list.tagName !== "UL") {
        list = document.createElement("ul");
        container.append(list);
      }
      const item = document.createElement("li");
      appendInlineMarkdown(item, bullet[1]);
      list.append(item);
      continue;
    }
    list = null;
    const paragraph = document.createElement("p");
    appendInlineMarkdown(paragraph, line);
    container.append(paragraph);
  }
}

function renderCodeBlock(container, code, language = "") {
  const wrapper = document.createElement("div");
  wrapper.className = "code-block";
  const header = document.createElement("div");
  header.className = "code-block-header";
  const label = document.createElement("span");
  label.textContent = language || "code";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "copy-code-button";
  button.textContent = "复制";
  button.addEventListener("click", async () => {
    await navigator.clipboard?.writeText(code);
    button.textContent = "已复制";
    window.setTimeout(() => {
      button.textContent = "复制";
    }, 1200);
  });
  const pre = document.createElement("pre");
  const codeNode = document.createElement("code");
  codeNode.textContent = code;
  pre.append(codeNode);
  header.append(label, button);
  wrapper.append(header, pre);
  container.append(wrapper);
}

function isMarkdownTable(lines, index) {
  const current = lines[index] || "";
  const next = lines[index + 1] || "";
  return current.includes("|") && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(next);
}

function renderMarkdownTable(container, lines) {
  const table = document.createElement("table");
  table.className = "markdown-table";
  const head = document.createElement("thead");
  const body = document.createElement("tbody");
  const [headerLine, , ...bodyLines] = lines;
  const headerRow = document.createElement("tr");
  for (const cell of splitTableRow(headerLine)) {
    const th = document.createElement("th");
    appendInlineMarkdown(th, cell);
    headerRow.append(th);
  }
  head.append(headerRow);
  for (const line of bodyLines) {
    const row = document.createElement("tr");
    for (const cell of splitTableRow(line)) {
      const td = document.createElement("td");
      appendInlineMarkdown(td, cell);
      row.append(td);
    }
    body.append(row);
  }
  table.append(head, body);
  container.append(table);
}

function splitTableRow(line) {
  return String(line)
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function appendInlineMarkdown(parent, text) {
  const pattern = /(\[[^\]]+\]\((https?:\/\/[^)\s]+|mailto:[^)\s]+)\)|\*\*[^*]+\*\*|`[^`]+`)/g;
  let lastIndex = 0;
  for (const match of String(text).matchAll(pattern)) {
    parent.append(document.createTextNode(String(text).slice(lastIndex, match.index)));
    const token = match[0];
    if (token.startsWith("[")) {
      const labelEnd = token.indexOf("]");
      const href = token.slice(labelEnd + 2, -1);
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.textContent = token.slice(1, labelEnd);
      anchor.rel = "noreferrer";
      anchor.target = "_blank";
      parent.append(anchor);
    } else if (token.startsWith("**")) {
      const strong = document.createElement("strong");
      strong.textContent = token.slice(2, -2);
      parent.append(strong);
    } else {
      const code = document.createElement("code");
      code.textContent = token.slice(1, -1);
      parent.append(code);
    }
    lastIndex = match.index + token.length;
  }
  parent.append(document.createTextNode(String(text).slice(lastIndex)));
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

async function sendChatTurn(message) {
  if (!message) {
    els.messageInput.focus();
    return;
  }
  els.sendButton.disabled = true;
  startLiveTurn(message);
  try {
    const started = await postJson("/api/chat/start", {
      session_id: state.sessionId,
      message,
    });
    state.sessionId = started.session_id;
    state.activeJobId = started.job_id;
    if (state.liveTurn) {
      state.liveTurn.session_id = started.session_id;
      state.liveTurn.job_id = started.job_id;
    }
    els.sessionChip.textContent = `session: ${started.session_id}`;
    openChatEventSource(started.job_id);
  } catch (error) {
    if (isMissingChatStartEndpoint(error)) {
      renderResultNotice("当前页面连到旧后端，已临时切到同步模式；请关闭旧 8765 页面，重新用 start-agent.cmd 打开它显示的新地址。", "approval_required");
      await sendChatTurnLegacy(message);
      return;
    }
    stopLiveTurn();
    els.sendButton.disabled = false;
    renderResultNotice(error instanceof Error ? error.message : String(error), "error");
    els.messageInput.focus();
  }
}

function isMissingChatStartEndpoint(error) {
  const message = error instanceof Error ? error.message : String(error);
  return message.includes("Unknown endpoint: /api/chat/start") || error?.status === 404;
}

async function sendChatTurnLegacy(message, { approveOnce = false } = {}) {
  try {
    const turn = await postJson(LEGACY_CHAT_TURN_ENDPOINT, {
      session_id: state.sessionId,
      message,
      approve_once: approveOnce,
    });
    state.sessionId = turn.session_id;
    els.sessionChip.textContent = `session: ${turn.session_id}`;
    stopLiveTurn();
    if (turn.approval_required) {
      showApprovalPanel(
        `审批 ${turn.requested_action}`,
        friendlyChatText(turn.last_observation_summary || "这个操作需要你先批准。"),
        async () => sendChatTurnLegacy(message, { approveOnce: true }),
      );
    } else {
      hideApprovalPanel();
      els.messageInput.value = "";
      autoResizeMessageInput();
    }
    await refreshWorkbench();
    await selectChat(turn.session_id);
    await selectRun(turn.run_id);
  } catch (error) {
    stopLiveTurn();
    renderResultNotice(error instanceof Error ? error.message : String(error), "error");
  } finally {
    els.sendButton.disabled = false;
    els.messageInput.focus();
  }
}

function startLiveTurn(userMessage) {
  closeChatEventSource();
  const existing = state.selectedChat?.turns || [];
  state.animateLatestRunId = "__pending__";
  state.liveEvents = [];
  state.liveTurn = {
    user: userMessage,
    run_id: "__pending__",
    final: "正在运行...",
    terminal_reason: "pending",
    status: "running",
    thinking_text: "执行过程",
    events: [],
    job_id: null,
    session_id: state.sessionId,
  };
  renderChatThread(existing);
}

function openChatEventSource(jobId) {
  closeChatEventSource();
  const source = new EventSource(`/api/chat/events?job_id=${encodeURIComponent(jobId)}`);
  state.eventSource = source;
  for (const eventName of [
    "chat_started",
    "model_call_start",
    "model_stream_start",
    "action_parsed",
    "tool_start",
    "approval_required",
    "approval_granted",
    "approval_denied",
    "observation",
    "final",
    "error",
  ]) {
    source.addEventListener(eventName, handleChatEvent);
  }
  source.onerror = () => {
    if (!state.liveTurn) {
      return;
    }
    renderResultNotice("事件流连接中断。", "error");
    closeChatEventSource();
    els.sendButton.disabled = false;
  };
}

function handleChatEvent(event) {
  const payload = JSON.parse(event.data);
  state.liveEvents.push(payload);
  if (state.liveTurn) {
    state.liveTurn.events = [...state.liveEvents];
    state.liveTurn.run_id = payload.run_id || state.liveTurn.run_id;
    state.liveTurn.final = liveTurnText(payload);
    state.liveTurn.terminal_reason = payload.terminal_reason || "pending";
    state.liveTurn.status = payload.status || "running";
  }
  renderChatThread(state.selectedChat?.turns || []);
  if (payload.event === "final") {
    finishLiveTurn(payload);
  } else if (payload.event === "error") {
    stopLiveTurn();
    els.sendButton.disabled = false;
  }
}

function liveTurnText(event) {
  if (event.event === "final") {
    return event.final || event.last_observation_summary || "已完成。";
  }
  if (event.event === "error") {
    return event.error || "运行出错。";
  }
  if (event.event === "approval_required") {
    return "等待审批。";
  }
  return "正在运行...";
}

async function finishLiveTurn(event) {
  closeChatEventSource();
  stopLiveTurn();
  hideApprovalPanel();
  els.messageInput.value = "";
  autoResizeMessageInput();
  els.sendButton.disabled = false;
  await refreshWorkbench();
  await selectChat(event.session_id);
  await selectRun(event.run_id);
  if (event.has_repair_noise) {
    els.runState.textContent = `已修复 ${event.repair_count} 次`;
  }
  els.messageInput.focus();
}

function stopLiveTurn() {
  state.liveTurn = null;
  state.liveEvents = [];
  state.activeJobId = null;
}

function closeChatEventSource() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
}

async function submitApproval(jobId, approve, button) {
  if (button) {
    button.disabled = true;
  }
  await postJson("/api/chat/approval", { job_id: jobId, approve });
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
  renderPagedList(els.resourceRunList, state.runs, "runs", runPreviewItem, "还没有运行记录。", 4);
}

function renderPagedList(container, records, pageKey, renderItem, emptyText, pageSize = 6) {
  if (!container) {
    return;
  }
  if (!records.length) {
    container.replaceChildren(emptyStateElement(emptyText));
    return;
  }
  const maxPage = Math.max(0, Math.ceil(records.length / pageSize) - 1);
  const page = Math.min(state.resourcePages[pageKey] || 0, maxPage);
  state.resourcePages[pageKey] = page;
  const start = page * pageSize;
  const items = records.slice(start, start + pageSize).map(renderItem);
  const footer = document.createElement("div");
  footer.className = "pagination-row";
  footer.addEventListener("click", (event) => event.stopPropagation());
  const prev = document.createElement("button");
  prev.type = "button";
  prev.textContent = "上一页";
  prev.disabled = page <= 0;
  prev.addEventListener("click", (event) => {
    event.stopPropagation();
    state.resourcePages[pageKey] = page - 1;
    renderResources();
    renderChats();
    renderRuns();
    renderSnapshots(state.selectedDetail?.snapshots || []);
  });
  const next = document.createElement("button");
  next.type = "button";
  next.textContent = "下一页";
  next.disabled = page >= maxPage;
  next.addEventListener("click", (event) => {
    event.stopPropagation();
    state.resourcePages[pageKey] = page + 1;
    renderResources();
    renderChats();
    renderRuns();
    renderSnapshots(state.selectedDetail?.snapshots || []);
  });
  const label = document.createElement("span");
  label.textContent = `${page + 1} / ${maxPage + 1}`;
  footer.append(prev, label, next);
  container.replaceChildren(...items, footer);
}

function runPreviewItem(run) {
  return resourcePreviewItem(
    run.run_id,
    `${run.status || "unknown"} / ${run.risk_level || "low"}`,
    new Date(run.updated_at).toLocaleString(),
  );
}

function resourcePreviewItem(title, detail, meta) {
  const item = document.createElement("article");
  item.className = "list-item resource-preview-item";
  item.innerHTML = '<strong></strong><span></span><small></small>';
  item.querySelector("strong").textContent = title;
  item.querySelector("span").textContent = detail;
  item.querySelector("small").textContent = meta;
  return item;
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
    els.fileList.replaceChildren(emptyStateElement(error instanceof Error ? error.message : String(error)));
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

function openResourceDetail(key) {
  if (!els.resourceDetailModal || !els.resourceDetailBody || !els.resourceDetailTitle) {
    return;
  }
  const titles = {
    summary: "状态概览",
    chats: "任务会话",
    runs: "运行记录",
    memory: "记忆状态",
    snapshots: "快照",
  };
  els.resourceDetailTitle.textContent = titles[key] || "详情";
  if (key === "chats") {
    replaceOrEmpty(els.resourceDetailBody, state.chats.map((chat) => chatButton(chat)), "还没有聊天会话。");
  } else if (key === "runs") {
    replaceOrEmpty(els.resourceDetailBody, state.runs.map((run) => runButton(run)), "还没有运行记录。");
  } else if (key === "memory") {
    const memory = state.health?.memory_review;
    replaceOrEmpty(els.resourceDetailBody, rowElements([
      ["Pending candidates", `${memory?.pending_count || 0}`],
      ["Active entries", `${memory?.active_count || 0}`],
      ["检查", (memory?.checks || []).join("；")],
    ]), "没有记忆记录。");
  } else if (key === "snapshots") {
    replaceOrEmpty(els.resourceDetailBody, (state.selectedDetail?.snapshots || []).map(snapshotItem), "这次运行没有快照。");
  } else {
    replaceOrEmpty(els.resourceDetailBody, rowElements([
      ["会话", `${state.chats.length}`],
      ["运行记录", `${state.runs.length}`],
      ["快照", `${state.selectedDetail?.snapshots?.length || 0}`],
      ["工作区风险", state.health?.workspace_risk?.risk_level || "low"],
    ]), "没有记录数据。");
  }
  els.resourceDetailModal.classList.remove("hidden");
}

function closeResourceDetail() {
  els.resourceDetailModal?.classList.add("hidden");
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
  renderPagedList(els.snapshotList, snapshots, "snapshots", snapshotPreviewItem, "这次运行没有快照。", 3);
}

function snapshotPreviewItem(snapshot) {
  return resourcePreviewItem(snapshot.path, snapshot.snapshot_path, "点击卡片查看操作");
}

function snapshotItem(snapshot) {
  const item = document.createElement("article");
  item.className = "trace-item";
  item.innerHTML = '<strong></strong><span></span><div class="row-actions"><button type="button">查看差异</button><button type="button">恢复</button></div>';
  item.querySelector("strong").textContent = snapshot.path;
  item.querySelector("span").textContent = snapshot.snapshot_path;
  const buttons = item.querySelectorAll("button");
  buttons[0].addEventListener("click", () => openDiff(snapshot.path, snapshot.snapshot_path));
  buttons[1].addEventListener("click", () => restoreSnapshot(snapshot));
  return item;
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
  replaceOrEmpty(container, rowElements(rows), "没有记录数据。");
}

function rowElements(rows) {
  return rows
    .filter(([, value]) => value)
    .map(([label, value]) => {
      const item = document.createElement("article");
      item.className = "trace-item";
      item.innerHTML = '<strong></strong><span></span>';
      item.querySelector("strong").textContent = label;
      item.querySelector("span").textContent = value;
      return item;
    });
}

function replaceOrEmpty(container, items, emptyText) {
  if (!container) {
    return;
  }
  if (!items.length) {
    container.replaceChildren(emptyStateElement(emptyText));
    return;
  }
  container.replaceChildren(...items);
}

function emptyStateElement(text) {
  const element = document.createElement("div");
  element.className = "empty-state";
  element.textContent = text;
  return element;
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
