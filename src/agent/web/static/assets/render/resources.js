import { state, els } from "../state.js";

import { renderRows, replaceOrEmpty, resourcePreviewItem, rowElements } from "./ui.js";

export function renderResources() {
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

export function openResourceDetail(key, actions = {}) {
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
  const chatItem = actions.chatItem || ((chat) =>
    resourcePreviewItem(chat.title || chat.latest_user || "chat", chat.latest_final || chat.status || "", `${chat.turn_count || 0}`));
  const runItem = actions.runItem || ((run) =>
    resourcePreviewItem(run.run_id, `${run.status || "unknown"} / ${run.risk_level || "low"}`, new Date(run.updated_at).toLocaleString()));
  const snapshotItemRenderer = actions.snapshotItem || ((snapshot) =>
    resourcePreviewItem(snapshot.path, snapshot.snapshot_path, "snapshot"));
  if (key === "chats") {
    replaceOrEmpty(els.resourceDetailBody, state.chats.map(chatItem), "还没有聊天会话。");
  } else if (key === "runs") {
    replaceOrEmpty(els.resourceDetailBody, state.runs.map(runItem), "还没有运行记录。");
  } else if (key === "memory") {
    const memory = state.health?.memory_review;
    replaceOrEmpty(els.resourceDetailBody, rowElements([
      ["Pending candidates", `${memory?.pending_count || 0}`],
      ["Active entries", `${memory?.active_count || 0}`],
      ["检查", (memory?.checks || []).join("；")],
    ]), "没有记忆记录。");
  } else if (key === "snapshots") {
    replaceOrEmpty(els.resourceDetailBody, (state.selectedDetail?.snapshots || []).map(snapshotItemRenderer), "这次运行没有快照。");
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

export function closeResourceDetail() {
  els.resourceDetailModal?.classList.add("hidden");
}
