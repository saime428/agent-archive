import { useCallback, useMemo, useState, type ReactNode } from "react";
import { MessageSquare, Save, ScrollText, Wrench } from "lucide-react";

import { api } from "../api/client";
import type {
  ChatSummary,
  ConfigPayload,
  ConfigUpdates,
  HealthPayload,
  RunListItem,
  ToolsPayload,
} from "../api/types";
import { Orb } from "../Orb";

interface SettingsViewProps {
  health: HealthPayload | null;
  config: ConfigPayload | null;
  configError: string | null;
  tools: ToolsPayload | null;
  chats: ChatSummary[];
  runs: RunListItem[];
  onSaved: (payload: ConfigPayload) => void;
  onOpenSession: (sessionId: string) => void;
  onOpenRun: (runId: string) => void;
}

// Exactly the backend write allowlist (web/settings.py::_validated_config_updates).
// Anything outside this set is displayed read-only and never posted.
type FormState = {
  provider: string;
  model: string;
  mode: string;
  sandbox: string;
  approval: string;
  dry_run: boolean;
  web_search_enabled: boolean;
  computer_read_enabled: boolean;
  native_tools: boolean;
  default_skills: string;
};

const PROVIDERS = ["fake", "deepseek", "openai-compat", "anthropic"];
const MODES = ["step", "guided", "auto", "plan-first"];
// The browser may only narrow these; the backend rejects danger-full-access and never.
const SANDBOXES = ["read-only", "workspace-write"];
const APPROVALS = ["risky-confirm", "always"];

function toForm(config: ConfigPayload): FormState {
  const record = config.config;
  return {
    provider: record.provider,
    model: record.model,
    mode: record.mode,
    sandbox: record.sandbox,
    approval: record.approval,
    dry_run: record.dry_run,
    web_search_enabled: record.web_search_enabled,
    computer_read_enabled: record.computer_read_enabled,
    native_tools: record.native_tools,
    default_skills: record.default_skills.join(", "),
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "保存失败。";
}

export function SettingsView({
  health,
  config,
  configError,
  tools,
  chats,
  runs,
  onSaved,
  onOpenSession,
  onOpenRun,
}: SettingsViewProps) {
  const [draft, setDraft] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const baseline = useMemo(() => (config ? toForm(config) : null), [config]);
  // Auto refresh must never clobber a draft: fall back to baseline only while clean.
  const form = draft ?? baseline;
  const dirty = draft !== null && baseline !== null && JSON.stringify(draft) !== JSON.stringify(baseline);
  // approval=never can only come from the global config; the browser must not resend it.
  const approvalLocked = baseline?.approval === "never";
  const sandboxLocked = baseline?.sandbox === "danger-full-access";

  const update = useCallback(
    <K extends keyof FormState>(key: K, value: FormState[K]) => {
      setSaved(false);
      setDraft((current) => ({ ...(current ?? (baseline as FormState)), [key]: value }));
    },
    [baseline],
  );

  const save = useCallback(async () => {
    if (!draft || !baseline) return;
    const updates: Partial<ConfigUpdates> = {};
    if (draft.provider !== baseline.provider) updates.provider = draft.provider;
    if (draft.model !== baseline.model) updates.model = draft.model;
    if (draft.mode !== baseline.mode) updates.mode = draft.mode;
    if (draft.sandbox !== baseline.sandbox && !sandboxLocked) updates.sandbox = draft.sandbox;
    if (draft.approval !== baseline.approval && !approvalLocked) updates.approval = draft.approval;
    if (draft.dry_run !== baseline.dry_run) updates.dry_run = draft.dry_run;
    if (draft.web_search_enabled !== baseline.web_search_enabled) updates.web_search_enabled = draft.web_search_enabled;
    if (draft.computer_read_enabled !== baseline.computer_read_enabled) {
      updates.computer_read_enabled = draft.computer_read_enabled;
    }
    if (draft.native_tools !== baseline.native_tools) updates.native_tools = draft.native_tools;
    if (draft.default_skills !== baseline.default_skills) {
      updates.default_skills = draft.default_skills.split(",").map((item) => item.trim()).filter(Boolean);
    }
    if (Object.keys(updates).length === 0) return;

    setSaving(true);
    setSaveError(null);
    try {
      const payload = await api.saveConfig(updates);
      setDraft(null);
      setSaved(true);
      onSaved(payload);
    } catch (error) {
      // Keep the dirty draft so the user does not lose edits on a server rejection.
      setSaveError(errorMessage(error));
    } finally {
      setSaving(false);
    }
  }, [draft, baseline, approvalLocked, sandboxLocked, onSaved]);

  const readiness = health?.settings_readiness;
  const risk = health?.workspace_risk;
  const memory = health?.memory_review;

  return (
    <section className="settings-view" aria-labelledby="system-heading">
      <h2 id="system-heading" className="sr-only">System</h2>

      <RunSectionLike title="配置检查">
        {readiness ? (
          <>
            <p className="overview-tag" data-tone={readiness.status === "ready" ? "ok" : "warning"}>
              {readiness.status}
            </p>
            <LabeledList label="检查" items={readiness.checks} />
            <KeyRow label="provider" value={`${readiness.provider} / ${readiness.model}`} />
            <KeyRow label="base_url" value={readiness.base_url || "（未设置）"} />
            <KeyRow
              label="API key"
              value={`${readiness.api_key_env ?? "无需 key"} · ${readiness.api_key_present ? "已配置" : "未配置"}${readiness.api_key_required ? "（必需）" : "（可选）"}`}
            />
            <LabeledList label="已加载配置文件" items={readiness.loaded_files} empty="无。" />
            <LabeledList label="配置警告" items={readiness.warnings} empty="无警告。" />
            <p className="overview-note">密钥只能在终端或 .agent/secrets.env 配置，浏览器不接收密钥。</p>
          </>
        ) : (
          <p className="overview-note" role="status"><Orb state="searching" /> 加载中。</p>
        )}
      </RunSectionLike>

      <RunSectionLike title="工作区风险">
        {risk ? (
          <>
            <p className="overview-tag" data-tone={risk.risk_level === "low" ? "ok" : "warning"}>{risk.risk_level}</p>
            <p className="overview-note" data-payload>{risk.summary}</p>
            <dl className="overview-signals">
              <div><dt>uncommitted</dt><dd>{risk.signals.uncommitted_files}</dd></div>
              <div><dt>failed runs</dt><dd>{risk.signals.failed_runs}</dd></div>
              <div><dt>snapshots</dt><dd>{risk.signals.snapshots}</dd></div>
            </dl>
            <LabeledList label="未提交文件" items={risk.uncommitted_files} empty="无未提交文件。" />
            <LabeledList label="检查" items={risk.checks} />
          </>
        ) : (
          <p className="overview-note" role="status">加载中。</p>
        )}
      </RunSectionLike>

      <RunSectionLike title="记忆审阅">
        {memory ? (
          <>
            <div className="run-key-row">
              <span className="run-key">计数</span>
              <span className="run-value">待确认 {memory.pending_count} · 生效 {memory.active_count}</span>
            </div>
            <LabeledList label="检查" items={memory.checks} />
            {memory.candidates.length ? (
              <div className="run-list-block">
                <span className="run-key">待确认候选</span>
                <ul className="memory-list">
                  {memory.candidates.map((item) => (
                    <li key={item.candidate_id} className="memory-item" data-payload>
                      <span className="memory-excerpt">{item.source_excerpt}</span>
                      <button type="button" className="files-action" onClick={() => onOpenRun(item.source_run_id)}>
                        来源 run
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {memory.entries.length ? (
              <div className="run-list-block">
                <span className="run-key">生效条目</span>
                <ul className="memory-list">
                  {memory.entries.map((item) => (
                    <li key={item.entry_id} className="memory-item" data-payload>
                      <span className="memory-excerpt">{item.source_excerpt}</span>
                      <button type="button" className="files-action" onClick={() => onOpenRun(item.source_run_id)}>
                        来源 run
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            <p className="overview-note">只读视图：确认或撤销 memory 请使用终端命令。</p>
          </>
        ) : (
          <p className="overview-note" role="status">加载中。</p>
        )}
      </RunSectionLike>

      <RunSectionLike title="运行设置">
        {configError ? <p className="overview-error" data-payload>{configError}</p> : null}
        {!form ? (
          <p className="overview-note" role="status">加载中。</p>
        ) : (
          <form
            className="settings-form"
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
          >
            <label className="settings-field">
              <span>provider</span>
              <select aria-label="provider" value={form.provider} onChange={(e) => update("provider", e.target.value)}>
                {PROVIDERS.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <label className="settings-field">
              <span>model</span>
              <input aria-label="model" type="text" value={form.model} onChange={(e) => update("model", e.target.value)} />
            </label>
            <label className="settings-field">
              <span>mode</span>
              <select aria-label="mode" value={form.mode} onChange={(e) => update("mode", e.target.value)}>
                {MODES.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <label className="settings-field">
              <span>sandbox</span>
              {sandboxLocked ? (
                <span className="overview-tag" data-tone="warning">
                  当前为 danger-full-access（来自全局配置），浏览器不修改该值
                </span>
              ) : (
                <select aria-label="sandbox" value={form.sandbox} onChange={(e) => update("sandbox", e.target.value)}>
                  {SANDBOXES.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              )}
            </label>
            <label className="settings-field">
              <span>approval</span>
              {approvalLocked ? (
                <span className="overview-tag" data-tone="warning">
                  当前为 never（来自全局配置），浏览器不修改该值
                </span>
              ) : (
                <select aria-label="approval" value={form.approval} onChange={(e) => update("approval", e.target.value)}>
                  {APPROVALS.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              )}
            </label>
            <label className="settings-field">
              <span>default_skills</span>
              <input
                aria-label="default_skills"
                type="text"
                value={form.default_skills}
                onChange={(e) => update("default_skills", e.target.value)}
              />
            </label>

            <div className="settings-toggles">
              {([
                ["dry_run", "dry_run"],
                ["web_search_enabled", "web_search_enabled"],
                ["computer_read_enabled", "computer_read_enabled"],
                ["native_tools", "native_tools"],
              ] as const).map(([key, label]) => (
                <label key={key} className="settings-toggle">
                  <input
                    type="checkbox"
                    aria-label={label}
                    checked={form[key]}
                    onChange={(e) => update(key, e.target.checked)}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>

            <div className="settings-readonly">
              <KeyRow label="base_url" value={config?.config.base_url || "（未设置）"} />
              <KeyRow label="allowed_commands" value={config?.config.allowed_commands.join(", ") || "（空）"} />
              <KeyRow label="terminal_enabled" value={String(config?.config.terminal_enabled ?? false)} />
              <p className="overview-note">上面三项与密钥不在浏览器写白名单内，请用 CLI 修改。</p>
            </div>

            {saveError ? <p className="overview-error" data-payload>{saveError}</p> : null}
            {saved ? <p className="files-saved">设置已保存。</p> : null}
            <div className="files-confirm-actions">
              <button type="submit" className="files-action primary" disabled={!dirty || saving}>
                <Save aria-hidden="true" /> 保存设置
              </button>
              <button type="button" className="files-action" disabled={!dirty || saving} onClick={() => setDraft(null)}>
                放弃修改
              </button>
            </div>
          </form>
        )}
      </RunSectionLike>

      <RunSectionLike title="可用工具">
        {tools ? (
          <ul className="tools-list">
            {tools.tools.map((tool) => (
              <li key={tool.name} className="tools-item" data-payload>
                <Wrench aria-hidden="true" />
                <span className="tools-name">{tool.name}</span>
                <span className="overview-tag">{tool.category}</span>
                <span className="tools-dry">dry_run: {tool.dry_run}</span>
                <span className="tools-desc">{tool.description}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="overview-note" role="status">加载中。</p>
        )}
      </RunSectionLike>

      <RunSectionLike title="工作区资源">
        <div className="resource-grid">
          <div className="run-list-block">
            <span className="run-key"><MessageSquare aria-hidden="true" /> 会话 ({chats.length})</span>
            <ul className="resource-list">
              {chats.slice(0, 8).map((chat) => (
                <li key={chat.session_id}>
                  <button type="button" className="resource-link" onClick={() => onOpenSession(chat.session_id)}>
                    <span data-payload title={chat.title || chat.session_id}>{chat.title || chat.session_id}</span>
                    <span className="resource-meta">{chat.turn_count} 轮</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div className="run-list-block">
            <span className="run-key"><ScrollText aria-hidden="true" /> 运行 ({runs.length})</span>
            <ul className="resource-list">
              {runs.slice(0, 8).map((run) => (
                <li key={run.run_id}>
                  <button type="button" className="resource-link" onClick={() => onOpenRun(run.run_id)}>
                    <span data-payload title={run.run_id}>{run.run_id}</span>
                    <span className="resource-meta">{run.status}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </RunSectionLike>
    </section>
  );
}

function RunSectionLike({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="run-section" aria-labelledby={`settings-section-${title}`}>
      <h3 id={`settings-section-${title}`} className="run-section-title">{title}</h3>
      {children}
    </section>
  );
}

function KeyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="run-key-row">
      <span className="run-key">{label}</span>
      <span className="run-value" data-payload>{value}</span>
    </div>
  );
}

function LabeledList({ label, items, empty }: { label: string; items: string[]; empty?: string }) {
  return (
    <div className="run-list-block">
      <span className="run-key">{label}</span>
      {items.length === 0 ? (
        <span className="overview-note">{empty ?? "无。"}</span>
      ) : (
        <ul className="run-plain-list">
          {items.map((item, index) => <li key={`${item}-${index}`} data-payload>{item}</li>)}
        </ul>
      )}
    </div>
  );
}
