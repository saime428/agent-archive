import { state, els } from "../state.js";

import { renderPagedList, replaceOrEmpty, resourcePreviewItem } from "./ui.js";

export function renderRuns(onSelectRun, onPageChange) {
  const items = state.runs.map((run) => runButton(run, onSelectRun));
  replaceOrEmpty(els.runList, items, "还没有运行记录。");
  renderPagedList(els.resourceRunList, state.runs, "runs", runPreviewItem, "还没有运行记录。", 4, onPageChange);
}

function runPreviewItem(run) {
  return resourcePreviewItem(
    run.run_id,
    `${run.status || "unknown"} / ${run.risk_level || "low"}`,
    new Date(run.updated_at).toLocaleString(),
  );
}

export function runButton(run, onSelectRun) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `list-item${run.run_id === state.selectedRunId ? " selected" : ""}`;
  button.innerHTML = '<strong></strong><span></span><small></small>';
  button.querySelector("strong").textContent = run.run_id;
  button.querySelector("span").textContent = `${run.status || "unknown"} / ${run.risk_level || "low"}`;
  button.querySelector("small").textContent = new Date(run.updated_at).toLocaleString();
  button.addEventListener("click", () => onSelectRun?.(run.run_id));
  return button;
}
