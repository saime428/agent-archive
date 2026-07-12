import { state, els } from "../state.js";

import { postJson } from "../api.js";

import { renderRows } from "./ui.js";

export function renderHealth() {
  const health = state.health || {};
  els.workspace.textContent = health.workspace || "workspace";
  els.model.textContent = health.model || "DeepSeek";
  const webEnabled = Boolean(state.config?.config?.web_search_enabled);
  renderChipToggles();
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

export function renderSettings() {
  const config = state.config?.config || {};
  els.settingsProvider.value = config.provider || "deepseek";
  els.settingsModel.value = config.model || "deepseek-v4-flash";
  els.settingsSandbox.value = config.sandbox || "workspace-write";
  els.settingsApproval.value = config.approval || "risky-confirm";
  els.settingsSkills.value = (config.default_skills || ["code-dev"]).join(", ");
  els.settingsDryRun.checked = Boolean(config.dry_run);
  els.settingsWebSearch.checked = Boolean(config.web_search_enabled);
  els.settingsComputerRead.checked = Boolean(config.computer_read_enabled);
  els.settingsNativeTools.checked = Boolean(config.native_tools);
  const readiness = state.health?.settings_readiness || {};
  renderRows(els.settingsReadinessList, [
    ["状态", readiness.status || "ready"],
    ["服务商", readiness.provider || config.provider || "unknown"],
    ["模型", readiness.model || config.model || "unknown"],
    ["DeepSeek key", readiness.deepseek_api_key_present ? "已配置" : "缺失"],
    ["联网搜索", config.web_search_enabled ? "开" : "关"],
    ["读取电脑文件", config.computer_read_enabled ? "开（只读）" : "关"],
    ["命令白名单", (config.allowed_commands || []).join(", ") || "未配置"],
  ]);
  renderRows(
    els.settingsToolList,
    state.tools.map((tool) => [tool.name, `${tool.category} / dry-run: ${tool.dry_run}`]),
  );
}

export async function saveSettings(event, refreshWorkbench) {
  event.preventDefault();
  await saveSettingsValues("设置已保存。", refreshWorkbench);
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
    native_tools: els.settingsNativeTools.checked,
    default_skills: els.settingsSkills.value.split(",").map((item) => item.trim()).filter(Boolean),
  };
}

export async function saveSettingsValues(successText, refreshWorkbench) {
  const payload = {
    ...buildSettingsPayload(),
  };
  try {
    els.settingsStatus.textContent = "正在保存设置...";
    state.config = await postJson("/api/config", payload);
    if (typeof refreshWorkbench === "function") {
      await refreshWorkbench();
    }
    els.settingsStatus.textContent = successText || "设置已保存。";
  } catch (error) {
    els.settingsStatus.textContent = error instanceof Error ? error.message : String(error);
  }
}

const CHIP_TOGGLE_LABELS = {
  web_search_enabled: "联网",
  computer_read_enabled: "电脑文件",
  native_tools: "原生工具",
};

export function renderChipToggles() {
  const config = state.config?.config || {};
  const toggles = [
    [els.webSearchToggle, "web_search_enabled"],
    [els.computerReadToggle, "computer_read_enabled"],
    [els.nativeToolsToggle, "native_tools"],
  ];
  for (const [button, key] of toggles) {
    if (!button) {
      continue;
    }
    const enabled = Boolean(config[key]);
    button.textContent = `${CHIP_TOGGLE_LABELS[key]}：${enabled ? "开" : "关"}`;
    button.classList.toggle("on", enabled);
    button.setAttribute("aria-pressed", String(enabled));
  }
}

export async function toggleConfigKey(key, button, refreshWorkbench) {
  const current = Boolean(state.config?.config?.[key]);
  button.disabled = true;
  try {
    state.config = await postJson("/api/config", { [key]: !current });
    renderChipToggles();
    if (typeof refreshWorkbench === "function") {
      await refreshWorkbench();
    }
  } catch (error) {
    els.settingsStatus.textContent = error instanceof Error ? error.message : String(error);
    renderChipToggles();
  } finally {
    button.disabled = false;
  }
}
