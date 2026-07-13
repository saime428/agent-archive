import { els } from "../state.js";

import { renderPagedList, renderRows, resourcePreviewItem } from "./ui.js";

export function renderDiagnostics(detail, snapshotActions = {}) {
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
    renderSnapshots([], snapshotActions);
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

export function renderRunReplay(replay) {
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

export function renderToolCalls(toolCalls) {
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
      const warning = call.data?.trace?.warning;
      return [`${call.line_number}. ${action}`, warning ? `${warning}\n${summary}` : summary];
    }),
  );
}

export function renderTerminal(detail) {
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

export function renderSnapshots(snapshots, actions = {}) {
  if (!els.snapshotList) {
    return;
  }
  if (!snapshots.length) {
    els.snapshotList.innerHTML = '<div class="empty-state">这次运行没有快照。</div>';
    return;
  }
  renderPagedList(els.snapshotList, snapshots, "snapshots", snapshotPreviewItem, "这次运行没有快照。", 3, actions.onPageChange);
}

function snapshotPreviewItem(snapshot) {
  return resourcePreviewItem(snapshot.path, snapshot.snapshot_path, "点击卡片查看操作");
}

export function snapshotItem(snapshot, actions = {}) {
  const item = document.createElement("article");
  item.className = "trace-item";
  item.innerHTML = '<strong></strong><span></span><div class="row-actions"><button type="button">查看差异</button><button type="button">恢复</button></div>';
  item.querySelector("strong").textContent = snapshot.path;
  item.querySelector("span").textContent = snapshot.snapshot_path;
  const buttons = item.querySelectorAll("button");
  buttons[0].addEventListener("click", () => actions.openDiff?.(snapshot.path, snapshot.snapshot_path));
  buttons[1].addEventListener("click", () => actions.restoreSnapshot?.(snapshot));
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
