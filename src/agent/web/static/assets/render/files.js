import { state, els } from "../state.js";

import { loadJson } from "../api.js";

import { emptyStateElement, parentPath, replaceOrEmpty } from "./ui.js";

import { openFile, renderEditorHome } from "./editor.js";

export async function loadFiles(path) {
  try {
    const payload = await loadJson(`/api/files?path=${encodeURIComponent(path)}`);
    renderFiles(payload.entries || [], payload.path || ".");
  } catch (error) {
    els.fileList.replaceChildren(emptyStateElement(error instanceof Error ? error.message : String(error)));
  }
}

export function renderFiles(entries, currentPath) {
  state.fileEntries = entries;
  state.fileCurrentPath = currentPath;
  renderFileEntries();
  renderEditorHome(fileButton);
}

export function renderFileEntries() {
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
  renderEditorHome(fileButton);
}

export function fileButton(name, path, kind) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "list-item";
  button.innerHTML = '<strong></strong><span></span>';
  button.querySelector("strong").textContent = name;
  button.querySelector("span").textContent = `${kind} - ${path}`;
  button.addEventListener("click", () => (kind === "dir" ? loadFiles(path) : openFile(path)));
  return button;
}
