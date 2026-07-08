import { state, els } from "../state.js";

import { loadJson, postJson } from "../api.js";

import { activateView, replaceOrEmpty } from "./ui.js";

export function renderEditorHome(fileButton) {
  const files = state.fileEntries
    .filter((entry) => entry.kind !== "dir")
    .slice(0, 8)
    .map((entry) => fileButton(entry.name, entry.path, entry.kind));
  replaceOrEmpty(els.recentFileList, files, "当前目录没有可打开的文件。");
}

export async function openFile(path) {
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

export async function saveOpenFile({ showApprovalPanel, refreshWorkbench, loadFiles, selectRun } = {}) {
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

export function showSummary(text, title = "摘要") {
  els.selectedFileTitle.textContent = title;
  els.fileEditor.classList.add("hidden");
  els.saveFileButton.classList.add("hidden");
  els.summary.classList.remove("hidden");
  els.summary.textContent = text;
  activateView("editor");
}
