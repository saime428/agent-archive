import { state, els } from "../state.js";


export function applyStoredTheme() {
  const theme = localStorage.getItem("agent-theme");
  if (theme === "dark" || theme === "light") {
    document.documentElement.dataset.theme = theme;
  }
  updateThemeButton();
}

export function toggleTheme() {
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

export function initColumnResize() {
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

export function activateView(view) {
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

export function scrollToSetting(targetId) {
  activateView("settings");
  for (const button of els.settingsNavButtons) {
    button.classList.toggle("active", button.dataset.settingsTarget === targetId);
  }
  document.getElementById(targetId)?.scrollIntoView({ block: "center", behavior: "smooth" });
}

export function activateSidePanel(panel) {
  state.activeSidePanel = panel || "review";
  for (const button of els.sideTabButtons) {
    button.classList.toggle("active", button.dataset.sidePanel === state.activeSidePanel);
  }
  for (const section of els.sidePanels) {
    section.classList.toggle("active", section.dataset.sidePanel === state.activeSidePanel);
  }
}

export function renderResultNotice(text, display_status) {
  const notice = document.createElement("article");
  notice.className = `result-notice ${display_status || "ok"}`;
  notice.textContent = text;
  els.chatThread.append(notice);
}

export function showActionError(prefix, error) {
  globalThis.alert(`${prefix}: ${backendErrorMessage(error)}`);
}

function backendErrorMessage(error) {
  const message = error instanceof Error ? error.message : String(error);
  if (error?.status === 404) {
    return `${message}。当前页面连到的后端不是最新进程，请关闭旧 8765 页面，重新用 start-agent.cmd 打开它显示的新地址。`;
  }
  return message;
}

export function renderPagedList(container, records, pageKey, renderItem, emptyText, pageSize = 6, onPageChange = null) {
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
    onPageChange?.();
  });
  const next = document.createElement("button");
  next.type = "button";
  next.textContent = "下一页";
  next.disabled = page >= maxPage;
  next.addEventListener("click", (event) => {
    event.stopPropagation();
    state.resourcePages[pageKey] = page + 1;
    onPageChange?.();
  });
  const label = document.createElement("span");
  label.textContent = `${page + 1} / ${maxPage + 1}`;
  footer.append(prev, label, next);
  container.replaceChildren(...items, footer);
}

export function resourcePreviewItem(title, detail, meta) {
  const item = document.createElement("article");
  item.className = "list-item resource-preview-item";
  item.innerHTML = '<strong></strong><span></span><small></small>';
  item.querySelector("strong").textContent = title;
  item.querySelector("span").textContent = detail;
  item.querySelector("small").textContent = meta;
  return item;
}

export function renderRows(container, rows) {
  if (!container) {
    return;
  }
  replaceOrEmpty(container, rowElements(rows), "没有记录数据。");
}

export function rowElements(rows) {
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

export function replaceOrEmpty(container, items, emptyText) {
  if (!container) {
    return;
  }
  if (!items.length) {
    container.replaceChildren(emptyStateElement(emptyText));
    return;
  }
  container.replaceChildren(...items);
}

export function emptyStateElement(text) {
  const element = document.createElement("div");
  element.className = "empty-state";
  element.textContent = text;
  return element;
}

export function parentPath(path) {
  if (/^[A-Za-z]:\\/.test(path) || path.includes("\\")) {
    const normalized = path.replace(/\\+$/, "");
    const index = normalized.lastIndexOf("\\");
    return index > 2 ? normalized.slice(0, index) : normalized;
  }
  const parts = path.split("/").filter(Boolean);
  parts.pop();
  return parts.length ? parts.join("/") : ".";
}
