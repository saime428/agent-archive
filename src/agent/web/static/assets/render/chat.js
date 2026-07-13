import { state, els, LEGACY_CHAT_TURN_ENDPOINT, SEARCH_DEBOUNCE_MS, debounce } from "../state.js";
import { loadJson, postJson } from "../api.js";
import { closeChatEventSource, openChatEventSource, submitApproval } from "../sse.js";
import {
  activateSidePanel,
  activateView,
  applyStoredTheme,
  initColumnResize,
  renderPagedList,
  renderResultNotice,
  renderRows,
  replaceOrEmpty,
  resourcePreviewItem,
  scrollToSetting,
  showActionError,
  toggleTheme,
} from "./ui.js";
import {
  renderChipToggles,
  renderHealth,
  renderSettings,
  saveSettings,
  saveSettingsValues,
  toggleConfigKey,
} from "./health.js";
import { renderRuns, runButton } from "./runs.js";
import { loadFiles, renderFileEntries } from "./files.js";
import { saveOpenFile, showSummary } from "./editor.js";
import { closeResourceDetail, openResourceDetail, renderResources } from "./resources.js";
import { renderDiagnostics, renderSnapshots, snapshotItem } from "./diagnostics.js";

export async function boot() {
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
  const debouncedChatSearch = debounce(() => {
    state.chatQuery = els.chatSearch.value.trim().toLowerCase();
    renderChats();
  }, SEARCH_DEBOUNCE_MS);
  const debouncedFileSearch = debounce(() => {
    state.fileQuery = els.fileSearch.value.trim().toLowerCase();
    renderFileEntries();
  }, SEARCH_DEBOUNCE_MS);
  els.chatSearch.addEventListener("input", debouncedChatSearch);
  els.fileSearch.addEventListener("input", debouncedFileSearch);
  els.chatForm.addEventListener("submit", submitChatTurn);
  els.messageInput.addEventListener("keydown", handleMessageKeydown);
  els.messageInput.addEventListener("input", autoResizeMessageInput);
  els.approveButton.addEventListener("click", approvePendingAction);
  els.denyButton.addEventListener("click", denyPendingAction);
  els.saveFileButton.addEventListener("click", () => saveOpenFile({ showApprovalPanel, refreshWorkbench, loadFiles, selectRun }));
  els.settingsForm.addEventListener("submit", (event) => saveSettings(event, refreshWorkbench));
  els.settingsWebSearch.addEventListener("change", () => saveSettingsValues("联网搜索设置已保存。", refreshWorkbench));
  els.settingsComputerRead.addEventListener("change", () => saveSettingsValues("电脑文件只读设置已保存。", refreshWorkbench));
  els.settingsNativeTools?.addEventListener("change", () => saveSettingsValues("原生工具设置已保存。", refreshWorkbench));
  els.webSearchToggle?.addEventListener("click", () => toggleConfigKey("web_search_enabled", els.webSearchToggle, refreshWorkbench));
  els.computerReadToggle?.addEventListener("click", () => toggleConfigKey("computer_read_enabled", els.computerReadToggle, refreshWorkbench));
  els.nativeToolsToggle?.addEventListener("click", () => toggleConfigKey("native_tools", els.nativeToolsToggle, refreshWorkbench));
  els.thinkingToggle?.addEventListener("click", toggleThinkingVisibility);
  applyThinkingVisibility();
  document.addEventListener("click", closeChatMenus);
  for (const panel of els.resourcePanels) {
    panel.addEventListener("click", () => openResourceDetail(panel.dataset.resourcePanel, resourceDetailActions()));
    panel.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") {
        return;
      }
      event.preventDefault();
      openResourceDetail(panel.dataset.resourcePanel, resourceDetailActions());
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
  renderRuns(selectRun, rerenderPagedLists);
  renderResources();
  if (selectInitial && state.chats.length && !state.sessionId) {
    await selectChat(state.chats[0].session_id);
  } else if (!state.selectedChat) {
    renderChatThread([]);
  }
  if ((selectInitial || !state.selectedRunId) && state.runs.length) {
    await selectRun(state.runs[0].run_id);
  } else if (!state.selectedDetail) {
    renderDiagnostics(null, snapshotActions());
  }
}

function rerenderPagedLists() {
  renderResources();
  renderChats();
  renderRuns(selectRun, rerenderPagedLists);
  renderSnapshots(state.selectedDetail?.snapshots || [], snapshotActions());
}

function snapshotActions() {
  return { openDiff, restoreSnapshot, onPageChange: rerenderPagedLists };
}

function resourceDetailActions() {
  return {
    chatItem: chatButton,
    runItem: (run) => runButton(run, selectRun),
    snapshotItem: (snapshot) => snapshotItem(snapshot, snapshotActions()),
  };
}


function renderChats() {
  const filtered = state.chats.filter((chat) => {
    const haystack = `${chat.latest_user || ""} ${chat.latest_final || ""} ${chat.status || ""}`.toLowerCase();
    return !state.chatQuery || haystack.includes(state.chatQuery);
  });
  const items = filtered.map((chat) => chatButton(chat));
  replaceOrEmpty(els.chatList, items, "还没有聊天会话。");
  replaceOrEmpty(els.resourceChatList, state.chats.map((chat) => chatButton(chat)), "还没有聊天会话。");
  renderPagedList(els.resourceChatMainList, state.chats, "chats", chatPreviewItem, "还没有聊天会话。", 4, rerenderPagedLists);
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
      liveTurn: isLiveTurn,
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
  if (options.liveTurn) {
    article.dataset.liveTurn = "true";
  }
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
    "Run commands execute local processes with the agent's OS permissions; workspace path checks do not fully contain file, network, or subprocess access. Approval is required.": "运行命令会以 Agent 当前的操作系统权限启动本地进程；工作区路径检查无法完整限制文件、网络或子进程访问。执行前需要你的批准。",
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
    if (!container.contains(target)) {
      container.classList.remove("typing");
      return;
    }
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
          ["approval_granted", "approval_denied", "approval_timed_out"].includes(item.event),
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
  if (event.event === "error" || event.status === "error" || ["approval_denied", "approval_timed_out"].includes(event.event)) {
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
    approval_timed_out: "审批超时",
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
    const reason = friendlyChatText(event.reason);
    return elapsed ? `${reason} · ${elapsed}` : reason;
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
    openChatEventSource(started.job_id, { onEvent: handleLiveChatEvent, onError: handleChatStreamError });
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

function handleLiveChatEvent(payload) {
  if (payload.event === "model_stream_chunk") {
    renderStreamChunk(payload);
    return;
  }
  state.liveEvents.push(payload);
  if (state.liveTurn) {
    state.liveTurn.events = [...state.liveEvents];
    state.liveTurn.run_id = payload.run_id || state.liveTurn.run_id;
    state.liveTurn.final = liveTurnText(payload);
    state.liveTurn.terminal_reason = payload.terminal_reason || "pending";
    state.liveTurn.status = payload.status || "running";
  }
  renderLiveTurnIncrement(payload);
  if (payload.event === "final") {
    finishLiveTurn(payload);
  } else if (payload.event === "error") {
    stopLiveTurn();
    els.sendButton.disabled = false;
  }
}

function handleChatStreamError() {
  if (!state.liveTurn) {
    return;
  }
  renderResultNotice("事件流连接中断。", "error");
  closeChatEventSource();
  els.sendButton.disabled = false;
}


function renderLiveTurnIncrement(event) {
  const article = els.chatThread.querySelector('[data-live-turn="true"]');
  if (!state.liveTurn || !article) {
    renderChatThread(state.selectedChat?.turns || []);
    return;
  }
  const bodyText = state.liveTurn.final || state.liveTurn.last_observation_summary || state.liveTurn.status || "姝ｅ湪杩愯...";
  const isTerminal = ["final", "error", "approval_timed_out"].includes(event.event);
  const isWaitingApproval = event.event === "approval_required";
  const body = article.querySelector(".message-body");
  if (body) {
    body.replaceChildren();
    if (isTerminal || isWaitingApproval) {
      renderMessageBody(body, friendlyChatText(bodyText));
    } else if (state.liveTurn.streamText) {
      body.textContent = state.liveTurn.streamText;
    } else {
      renderMessageSkeleton(body);
    }
  }
  const meta = article.querySelector(".message-meta");
  if (meta) {
    meta.textContent = friendlyTerminalReason(state.liveTurn.terminal_reason);
  }
  const details = article.querySelector(".thought-process");
  const summary = details?.querySelector("summary");
  const processBody = details?.querySelector(".thinking-copy");
  if (details && summary && processBody) {
    details.open = true;
    summary.textContent = processSummary(state.liveTurn.events || []);
    renderProcessCards(processBody, state.liveTurn.events || [], { jobId: state.liveTurn.job_id });
    attachLiveStreamNode(processBody);
  }
  els.chatThread.scrollTop = els.chatThread.scrollHeight;
}

function renderStreamChunk(payload) {
  if (!state.liveTurn || typeof payload.text !== "string" || !payload.text) {
    return;
  }
  const article = els.chatThread.querySelector('[data-live-turn="true"]');
  if (!article) {
    return;
  }
  if (payload.kind === "content") {
    state.liveTurn.streamText = (state.liveTurn.streamText || "") + payload.text;
    const body = article.querySelector(".message-body");
    if (body) {
      body.textContent = state.liveTurn.streamText;
    }
  } else {
    state.liveTurn.streamThinking = (state.liveTurn.streamThinking || "") + payload.text;
    const details = article.querySelector(".thought-process");
    const processBody = details?.querySelector(".thinking-copy");
    if (details && processBody) {
      details.open = true;
      attachLiveStreamNode(processBody);
    }
  }
  els.chatThread.scrollTop = els.chatThread.scrollHeight;
}

const THINKING_VISIBLE_KEY = "workbench-show-thinking";

function applyThinkingVisibility() {
  const visible = localStorage.getItem(THINKING_VISIBLE_KEY) !== "false";
  document.body.dataset.showThinking = String(visible);
  els.thinkingToggle?.setAttribute("aria-pressed", String(visible));
  els.thinkingToggle?.classList.toggle("on", visible);
}

function toggleThinkingVisibility() {
  const visible = localStorage.getItem(THINKING_VISIBLE_KEY) !== "false";
  localStorage.setItem(THINKING_VISIBLE_KEY, String(!visible));
  applyThinkingVisibility();
}

function attachLiveStreamNode(processBody) {
  if (!state.liveTurn?.streamThinking) {
    return;
  }
  let streamNode = processBody.querySelector('[data-stream-text="true"]');
  if (!streamNode) {
    streamNode = document.createElement("pre");
    streamNode.dataset.streamText = "true";
    streamNode.className = "stream-live-text";
    processBody.prepend(streamNode);
  }
  streamNode.textContent = state.liveTurn.streamThinking;
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
  if (event.event === "approval_timed_out") {
    return "审批超时。";
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

async function selectRun(runId) {
  const detail = await loadJson(`/api/runs/${encodeURIComponent(runId)}`);
  state.selectedRunId = detail.run_id;
  state.selectedDetail = detail;
  els.selectedRunTitle.textContent = detail.run_id;
  const lastCall = detail.tool_calls?.[detail.tool_calls.length - 1];
  els.runState.textContent = lastCall?.data?.observation?.status || "loaded";
  renderRuns(selectRun, rerenderPagedLists);
  renderDiagnostics(detail, snapshotActions());
  renderSnapshots(detail.snapshots || [], snapshotActions());
  renderResources();
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
