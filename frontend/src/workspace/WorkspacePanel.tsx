import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { FolderTree, LayoutDashboard, ListChecks, RefreshCw, X } from "lucide-react";

import { api } from "../api/client";
import type { ChatSummary, ConfigPayload, HealthPayload, RunsPayload, ToolsPayload } from "../api/types";
import { ConfirmDialog } from "./ConfirmDialog";
import { FilesView, type FilesViewHandle } from "./FilesView";
import { RunsView } from "./RunsView";
import { SettingsView } from "./SettingsView";

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
  onOpenSession: (sessionId: string) => void;
}

const VIEW_TABS: Array<{ id: WorkspaceView; label: string; icon: typeof FolderTree }> = [
  { id: "files", label: "Files", icon: FolderTree },
  { id: "runs", label: "Runs", icon: ListChecks },
  { id: "system", label: "System", icon: LayoutDashboard },
];

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败。";
}

export function WorkspacePanel({
  open,
  onOpenChange,
  health,
  chats,
  onGlobalRefresh,
  openerRef,
  onOpenSession,
}: WorkspacePanelProps) {
  const [view, setView] = useState<WorkspaceView>("system");
  const [runs, setRuns] = useState<Resource<RunsPayload>>(idleResource);
  const [config, setConfig] = useState<Resource<ConfigPayload>>(idleResource);
  const [tools, setTools] = useState<Resource<ToolsPayload>>(idleResource);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);
  const reducedMotion = useReducedMotion();
  // Same spring as the desktop session rail so both planes move with one motion language.
  const spring = reducedMotion ? { duration: 0 } : { type: "spring" as const, stiffness: 320, damping: 32, mass: 0.8 };
  const filesRef = useRef<FilesViewHandle>(null);
  const [pendingNav, setPendingNav] = useState<{ kind: "view"; view: WorkspaceView } | { kind: "close" } | null>(null);
  const [focusRunId, setFocusRunId] = useState<string | undefined>(undefined);

  // Resource / memory entries jump into the Runs detail for that run.
  const openRunFromResource = useCallback((runId: string) => {
    setFocusRunId(runId);
    setView("runs");
  }, []);

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

  // Leaving a dirty Files edit (tab switch or panel close) must be confirmed first.
  const leavingDirtyFiles = () => view === "files" && Boolean(filesRef.current?.isDirty());

  const requestView = (next: WorkspaceView) => {
    if (next !== "files" && leavingDirtyFiles()) setPendingNav({ kind: "view", view: next });
    else setView(next);
  };

  const handleOpenChange = (next: boolean) => {
    if (!next && leavingDirtyFiles()) setPendingNav({ kind: "close" });
    else onOpenChange(next);
  };

  const confirmPendingNav = () => {
    if (!pendingNav) return;
    if (pendingNav.kind === "view") setView(pendingNav.view);
    else onOpenChange(false);
    setPendingNav(null);
  };

  return (
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      <AnimatePresence>
        {open ? (
        <Dialog.Portal forceMount>
          <Dialog.Overlay asChild forceMount>
            <motion.div
              className="workspace-overlay"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={reducedMotion ? { duration: 0 } : { duration: 0.18 }}
            />
          </Dialog.Overlay>
          <Dialog.Content
            asChild
            forceMount
            aria-describedby={undefined}
            onCloseAutoFocus={(event) => {
              // Controlled Dialog has no Trigger; return focus to whichever button opened it.
              if (openerRef.current) {
                event.preventDefault();
                openerRef.current.focus();
              }
            }}
          >
            <motion.div
              className="workspace-plane"
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={spring}
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
                    onClick={() => requestView(tab.id)}
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
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={view}
                initial={reducedMotion ? false : { opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={reducedMotion ? { opacity: 1 } : { opacity: 0, y: -6 }}
                transition={reducedMotion ? { duration: 0 } : { duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
              >
                {view === "system" ? (
                  <>
                    <SystemOverview health={health} chats={chats} runs={runs} tools={tools} />
                    <SettingsView
                      health={health}
                      config={config.data}
                      configError={config.error}
                      tools={tools.data}
                      chats={chats}
                      runs={runs.data?.runs ?? []}
                      onSaved={(payload) => {
                        setConfig({ data: payload, error: null, loading: false });
                        void onGlobalRefresh();
                      }}
                      onOpenSession={(sessionId) => {
                        onOpenSession(sessionId);
                        onOpenChange(false);
                      }}
                      onOpenRun={openRunFromResource}
                    />
                  </>
                ) : view === "runs" ? (
                  <RunsView runs={runs.data?.runs ?? []} onGlobalRefresh={onGlobalRefresh} focusRunId={focusRunId} />
                ) : (
                  <FilesView ref={filesRef} />
                )}
              </motion.div>
            </AnimatePresence>
          </div>

          <ConfirmDialog
            open={pendingNav !== null}
            title="未保存修改"
            onOpenChange={(next) => !next && setPendingNav(null)}
            confirmLabel="丢弃并继续"
            cancelLabel="继续编辑"
            onConfirm={confirmPendingNav}
          >
            <p>
              当前文件有未保存修改。丢弃修改并
              {pendingNav?.kind === "close" ? "关闭工作台" : "切换视图"}？
            </p>
          </ConfirmDialog>
            </motion.div>
          </Dialog.Content>
        </Dialog.Portal>
        ) : null}
      </AnimatePresence>
    </Dialog.Root>
  );
}

// At-a-glance strip only; readiness / risk / memory / settings / tools detail lives in
// SettingsView below it so the System view stays one continuous surface, not a card wall.
function SystemOverview({
  health,
  chats,
  runs,
  tools,
}: {
  health: HealthPayload | null;
  chats: ChatSummary[];
  runs: Resource<RunsPayload>;
  tools: Resource<ToolsPayload>;
}) {
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
          <h3>Activity</h3>
          <dl className="overview-signals">
            <div><dt>chats</dt><dd>{chats.length}</dd></div>
            <div><dt>runs</dt><dd>{runs.data?.runs.length ?? "…"}</dd></div>
            <div><dt>tools</dt><dd>{tools.data?.tools.length ?? "…"}</dd></div>
          </dl>
          {runs.error ? <p className="overview-error">runs: {runs.error}</p> : null}
          {tools.error ? <p className="overview-error">tools: {tools.error}</p> : null}
        </article>
      </div>
    </section>
  );
}
