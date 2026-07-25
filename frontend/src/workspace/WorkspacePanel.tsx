import { useCallback, useEffect, useState, type RefObject } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { FolderTree, LayoutDashboard, ListChecks, RefreshCw, X } from "lucide-react";

import { api } from "../api/client";
import type { ChatSummary, ConfigPayload, HealthPayload, RunsPayload, ToolsPayload } from "../api/types";
import { FilesView } from "./FilesView";

type WorkspaceView = "files" | "runs" | "system";

const REFRESH_INTERVAL_MS = 10_000;

interface Resource<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

function idleResource<T>(): Resource<T> {
  return { data: null, error: null, loading: false };
}

interface WorkspacePanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  health: HealthPayload | null;
  chats: ChatSummary[];
  onGlobalRefresh: () => void | Promise<void>;
  openerRef: RefObject<HTMLButtonElement | null>;
}

const VIEW_TABS: Array<{ id: WorkspaceView; label: string; icon: typeof FolderTree }> = [
  { id: "files", label: "Files", icon: FolderTree },
  { id: "runs", label: "Runs", icon: ListChecks },
  { id: "system", label: "System", icon: LayoutDashboard },
];

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败。";
}

export function WorkspacePanel({ open, onOpenChange, health, chats, onGlobalRefresh, openerRef }: WorkspacePanelProps) {
  const [view, setView] = useState<WorkspaceView>("system");
  const [runs, setRuns] = useState<Resource<RunsPayload>>(idleResource);
  const [config, setConfig] = useState<Resource<ConfigPayload>>(idleResource);
  const [tools, setTools] = useState<Resource<ToolsPayload>>(idleResource);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setRuns((prev) => ({ ...prev, loading: true }));
    setConfig((prev) => ({ ...prev, loading: true }));
    setTools((prev) => ({ ...prev, loading: true }));
    // Each resource keeps its last success on failure; one failure never blanks the others.
    const [runsResult, configResult, toolsResult] = await Promise.allSettled([
      api.listRuns(),
      api.getConfig(),
      api.listTools(),
    ]);
    setRuns((prev) =>
      runsResult.status === "fulfilled"
        ? { data: runsResult.value, error: null, loading: false }
        : { ...prev, error: errorMessage(runsResult.reason), loading: false },
    );
    setConfig((prev) =>
      configResult.status === "fulfilled"
        ? { data: configResult.value, error: null, loading: false }
        : { ...prev, error: errorMessage(configResult.reason), loading: false },
    );
    setTools((prev) =>
      toolsResult.status === "fulfilled"
        ? { data: toolsResult.value, error: null, loading: false }
        : { ...prev, error: errorMessage(toolsResult.reason), loading: false },
    );
    void onGlobalRefresh();
    setLastRefresh(new Date().toLocaleTimeString());
  }, [onGlobalRefresh]);

  // First load on open; 10s safe refresh only while open and the tab is visible.
  useEffect(() => {
    if (!open) return;
    // loadAll only calls setState after its awaited fetches, so it cannot cascade renders here.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadAll();
    const tick = () => {
      if (document.visibilityState === "visible") void loadAll();
    };
    const timer = window.setInterval(tick, REFRESH_INTERVAL_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") void loadAll();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [open, loadAll]);

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="workspace-overlay" />
        <Dialog.Content
          className="workspace-plane"
          aria-describedby={undefined}
          onCloseAutoFocus={(event) => {
            // Controlled Dialog has no Trigger; return focus to whichever button opened it.
            if (openerRef.current) {
              event.preventDefault();
              openerRef.current.focus();
            }
          }}
        >
          <header className="workspace-head">
            <Dialog.Title className="workspace-title">工作台</Dialog.Title>
            <nav className="workspace-tabs" aria-label="工作台视图">
              {VIEW_TABS.map((tab) => {
                const Icon = tab.icon;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    className="workspace-tab"
                    aria-pressed={view === tab.id}
                    onClick={() => setView(tab.id)}
                  >
                    <Icon aria-hidden="true" />
                    {tab.label}
                  </button>
                );
              })}
            </nav>
            <div className="workspace-head-actions">
              {lastRefresh ? <span className="workspace-refresh-time">刷新于 {lastRefresh}</span> : null}
              <button type="button" className="icon-button" aria-label="刷新工作台" onClick={() => void loadAll()}>
                <RefreshCw aria-hidden="true" />
              </button>
              <Dialog.Close asChild>
                <button type="button" className="icon-button" aria-label="关闭工作台">
                  <X aria-hidden="true" />
                </button>
              </Dialog.Close>
            </div>
          </header>

          <div className="workspace-body">
            {view === "system" ? (
              <SystemOverview health={health} chats={chats} runs={runs} config={config} tools={tools} />
            ) : view === "runs" ? (
              <RunsPreview runs={runs} />
            ) : (
              <FilesView />
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function SystemOverview({
  health,
  chats,
  runs,
  config,
  tools,
}: {
  health: HealthPayload | null;
  chats: ChatSummary[];
  runs: Resource<RunsPayload>;
  config: Resource<ConfigPayload>;
  tools: Resource<ToolsPayload>;
}) {
  const risk = health?.workspace_risk;
  const readiness = health?.settings_readiness;
  return (
    <section className="workspace-section" aria-labelledby="system-overview-heading">
      <h2 id="system-overview-heading" className="workspace-section-title">
        System overview
      </h2>

      <div className="overview-grid">
        <article className="overview-card">
          <h3>Provider</h3>
          <p className="overview-lead" data-payload>
            {health ? `${health.provider} / ${health.model}` : "加载中"}
          </p>
          <p className="overview-note" data-payload>
            {health?.provider_notice ?? "Provider 状态加载中。"}
          </p>
          {readiness ? (
            <p className="overview-tag" data-tone={readiness.status === "ready" ? "ok" : "warning"}>
              settings: {readiness.status}
            </p>
          ) : null}
        </article>

        <article className="overview-card">
          <h3>Workspace risk</h3>
          {risk ? (
            <>
              <p className="overview-tag" data-tone={risk.risk_level === "low" ? "ok" : "warning"}>
                {risk.risk_level}
              </p>
              <p className="overview-note" data-payload>
                {risk.summary}
              </p>
              <dl className="overview-signals">
                <div><dt>uncommitted</dt><dd>{risk.signals.uncommitted_files}</dd></div>
                <div><dt>failed runs</dt><dd>{risk.signals.failed_runs}</dd></div>
                <div><dt>snapshots</dt><dd>{risk.signals.snapshots}</dd></div>
              </dl>
            </>
          ) : (
            <p className="overview-note">加载中。</p>
          )}
        </article>

        <article className="overview-card">
          <h3>Activity</h3>
          <dl className="overview-signals">
            <div><dt>chats</dt><dd>{chats.length}</dd></div>
            <div><dt>runs</dt><dd>{runs.data?.runs.length ?? "…"}</dd></div>
            <div><dt>tools</dt><dd>{tools.data?.tools.length ?? "…"}</dd></div>
          </dl>
          {runs.error ? <p className="overview-error">runs: {runs.error}</p> : null}
          {tools.error ? <p className="overview-error">tools: {tools.error}</p> : null}
        </article>

        <article className="overview-card">
          <h3>Settings</h3>
          {config.data ? (
            <dl className="overview-signals">
              <div><dt>mode</dt><dd data-payload>{config.data.config.mode}</dd></div>
              <div><dt>sandbox</dt><dd data-payload>{config.data.config.sandbox}</dd></div>
              <div><dt>approval</dt><dd data-payload>{config.data.config.approval}</dd></div>
            </dl>
          ) : (
            <p className="overview-note">{config.error ?? "加载中。"}</p>
          )}
        </article>
      </div>
    </section>
  );
}

// Task 4 会把 RunsView 详情/diff/restore 挂到这里；当前先展示真实 run 索引。
function RunsPreview({ runs }: { runs: Resource<RunsPayload> }) {
  return (
    <section className="workspace-section" aria-labelledby="runs-heading">
      <h2 id="runs-heading" className="workspace-section-title">Runs</h2>
      {runs.error ? <p className="overview-error">{runs.error}</p> : null}
      {runs.data && runs.data.runs.length > 0 ? (
        <ul className="runs-index">
          {runs.data.runs.map((run) => (
            <li key={run.run_id} className="runs-index-item" data-payload>
              <span className="runs-index-id">{run.run_id}</span>
              <span className="overview-tag" data-tone={run.risk_level === "low" ? "ok" : "warning"}>{run.risk_level}</span>
              <span className="runs-index-status">{run.status}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="overview-note">{runs.data === null && !runs.error ? "加载中。" : "暂无运行记录。"}</p>
      )}
    </section>
  );
}
