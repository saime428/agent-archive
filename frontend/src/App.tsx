import * as Dialog from "@radix-ui/react-dialog";
import * as Tooltip from "@radix-ui/react-tooltip";
import {
  Activity,
  Bot,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  CircleDashed,
  Clock3,
  Command,
  Folder,
  KeyRound,
  LoaderCircle,
  Menu,
  MessageSquare,
  Monitor,
  Moon,
  Orbit,
  Palette,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightOpen,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  SendHorizontal,
  Sun,
  Terminal,
  Trash2,
  TriangleAlert,
  Wifi,
  WifiOff,
  X,
  XCircle,
} from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { ContextField } from "./ContextField";
import { api, ApiError } from "./api/client";
import { subscribeChatJob, type StreamStatus } from "./api/sse";
import type { ChatEvent, ChatPayload, ChatSummary, ChatTurn, HealthPayload } from "./api/types";
import { chatReducer, initialChatState, recoveringState, type ChatPhase, type ChatState } from "./chat/state";
import { useTheme, type ModePreference, type ThemeName } from "./theme";
import { WorkspacePanel } from "./workspace/WorkspacePanel";

const ACTIVE_JOB_KEY = "agent.frontend.active-job";

interface ActiveJob {
  jobId: string;
  sessionId: string;
}

type SessionAction = { kind: "rename" | "delete"; chat: ChatSummary } | null;

const PHASE_COPY: Record<ChatPhase, { eyebrow: string; title: string; detail: string }> = {
  idle: { eyebrow: "SYSTEM READY", title: "READY", detail: "Describe the outcome. The agent will expose the path." },
  thinking: { eyebrow: "MODEL TRACE", title: "THINK", detail: "Building the next executable step." },
  stream: { eyebrow: "LIVE RESPONSE", title: "FLOW", detail: "The answer is arriving from the active run." },
  tool: { eyebrow: "LOCAL ACTION", title: "EXEC", detail: "The run is touching real tools and evidence." },
  approval: { eyebrow: "HUMAN GATE", title: "DECIDE", detail: "Execution is paused until you choose." },
  final: { eyebrow: "RUN COMPLETE", title: "DONE", detail: "The result is persisted in this session." },
  error: { eyebrow: "RUN INTERRUPTED", title: "FAULT", detail: "The failure is visible and recoverable." },
  recovering: { eyebrow: "HISTORY FALLBACK", title: "SYNC", detail: "Reconstructing the durable session state." },
};

function readActiveJob(): ActiveJob | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(ACTIVE_JOB_KEY) || "null") as Partial<ActiveJob> | null;
    return value && typeof value.jobId === "string" && typeof value.sessionId === "string"
      ? { jobId: value.jobId, sessionId: value.sessionId }
      : null;
  } catch {
    return null;
  }
}

function sessionFromHash(): string | null {
  const match = location.hash.match(/^#\/chat\/([^/]+)$/);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return null;
  }
}

function setSessionHash(sessionId: string | null) {
  const next = sessionId ? `#/chat/${encodeURIComponent(sessionId)}` : "#/new";
  if (location.hash !== next) location.hash = next;
}

function displayError(error: unknown) {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "请求未完成，请重试。";
}

function workspaceName(path: string) {
  return path.split(/[\\/]/).filter(Boolean).at(-1) || path || "workspace";
}

function shortDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date);
}

function IconButton({
  label,
  children,
  className = "",
  ...buttonProps
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string; children: ReactNode }) {
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>
        <button className={`icon-button ${className}`} aria-label={label} {...buttonProps}>
          {children}
        </button>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content className="tooltip" sideOffset={8}>
          {label}
          <Tooltip.Arrow className="tooltip-arrow" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

function StatusMark({ health }: { health: HealthPayload | null }) {
  if (!health) {
    return (
      <span className="command-status" data-tone="muted">
        <LoaderCircle className="spin" aria-hidden="true" /> Connecting
      </span>
    );
  }
  const ready = !health.api_key_required || health.api_key_present;
  return (
    <span className="command-status" data-tone={ready ? "ok" : "warning"}>
      {ready ? <KeyRound aria-hidden="true" /> : <TriangleAlert aria-hidden="true" />}
      {ready ? "Key ready" : "Key missing"}
    </span>
  );
}

function CommandSpine({
  health,
  onOpenSessions,
  onOpenWorkspace,
  canvasEnabled,
  onToggleCanvas,
}: {
  health: HealthPayload | null;
  onOpenSessions: () => void;
  onOpenWorkspace: (event: React.MouseEvent<HTMLButtonElement>) => void;
  canvasEnabled: boolean;
  onToggleCanvas: () => void;
}) {
  const { theme, mode, setTheme, setMode } = useTheme();
  const modeIcon = mode === "auto" ? <Monitor aria-hidden="true" /> : mode === "dark" ? <Moon aria-hidden="true" /> : <Sun aria-hidden="true" />;

  return (
    <header className="command-spine">
      <div className="command-brand">
        <IconButton label="打开会话" className="mobile-only" onClick={onOpenSessions}>
          <Menu aria-hidden="true" />
        </IconButton>
        <IconButton label="打开工作台" className="mobile-only" onClick={onOpenWorkspace}>
          <PanelRightOpen aria-hidden="true" />
        </IconButton>
        <Command aria-hidden="true" />
        <span>AGENT</span>
        <span className="brand-divider">/</span>
        <strong>{workspaceName(health?.workspace || "Workbench")}</strong>
      </div>

      <div className="command-context" aria-label="运行配置">
        <span className="context-item context-workspace" title={health?.workspace}>
          <Folder aria-hidden="true" />
          {health?.workspace || "Loading workspace"}
        </span>
        <span className="context-item" title={health?.provider_notice} aria-label={health?.provider_notice || "Provider pending"}>
          <Bot aria-hidden="true" />
          {health ? `${health.provider} / ${health.model}` : "Provider pending"}
        </span>
        <StatusMark health={health} />
      </div>

      <div className="command-controls">
        <label className="select-control" title="主题">
          <Palette aria-hidden="true" />
          <span className="sr-only">主题</span>
          <select value={theme} onChange={(event) => setTheme(event.target.value as ThemeName)} aria-label="主题">
            <option value="a">A / Signal</option>
            <option value="b">B / Spatial</option>
            <option value="c">C / Paper</option>
          </select>
        </label>
        <label className="select-control" title="显示模式">
          {modeIcon}
          <span className="sr-only">显示模式</span>
          <select value={mode} onChange={(event) => setMode(event.target.value as ModePreference)} aria-label="显示模式">
            <option value="auto">Auto</option>
            <option value="dark">Dark</option>
            <option value="light">Light</option>
          </select>
        </label>
        <IconButton label={canvasEnabled ? "关闭上下文画布" : "打开上下文画布"} onClick={onToggleCanvas}>
          {canvasEnabled ? <Orbit aria-hidden="true" /> : <CircleDashed aria-hidden="true" />}
        </IconButton>
      </div>
    </header>
  );
}

function SessionPanel({
  chats,
  selectedId,
  expanded,
  filter,
  onFilter,
  onNew,
  onSelect,
  onAction,
}: {
  chats: ChatSummary[];
  selectedId: string | null;
  expanded: boolean;
  filter: string;
  onFilter: (value: string) => void;
  onNew: () => void;
  onSelect: (sessionId: string) => void;
  onAction: (action: NonNullable<SessionAction>) => void;
}) {
  const filtered = useMemo(() => {
    const needle = filter.trim().toLocaleLowerCase();
    return needle
      ? chats.filter((chat) => `${chat.title} ${chat.latest_user}`.toLocaleLowerCase().includes(needle))
      : chats;
  }, [chats, filter]);

  return (
    <div className="session-panel">
      <button className="new-session" onClick={onNew} aria-label="新建任务">
        <Plus aria-hidden="true" />
        {expanded && <span>新建任务</span>}
      </button>
      {expanded && (
        <label className="session-search">
          <Search aria-hidden="true" />
          <span className="sr-only">搜索会话</span>
          <input value={filter} onChange={(event) => onFilter(event.target.value)} placeholder="搜索会话" />
        </label>
      )}
      <div className="session-list" aria-label="会话列表">
        {filtered.length === 0 && expanded ? <p className="session-empty">没有匹配的会话</p> : null}
        {filtered.map((chat) => {
          const active = chat.session_id === selectedId;
          return (
            <div className="session-row" data-active={active} key={chat.session_id}>
              <button className="session-link" onClick={() => onSelect(chat.session_id)} aria-current={active ? "page" : undefined}>
                <MessageSquare aria-hidden="true" />
                {expanded && (
                  <span className="session-copy">
                    <strong data-payload>{chat.title}</strong>
                    <small>{shortDate(chat.updated_at)} / {chat.status}</small>
                  </span>
                )}
              </button>
              {expanded && (
                <span className="session-actions">
                  <IconButton label="重命名会话" onClick={() => onAction({ kind: "rename", chat })}>
                    <Pencil aria-hidden="true" />
                  </IconButton>
                  <IconButton label="删除会话" className="danger-action" onClick={() => onAction({ kind: "delete", chat })}>
                    <Trash2 aria-hidden="true" />
                  </IconButton>
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function HistoryTurn({ turn, index, originalThinking }: { turn: ChatTurn; index: number; originalThinking?: string }) {
  const thinking = originalThinking || turn.thinking_text;
  return (
    <section className="turn" aria-label={`历史回合 ${index + 1}`}>
      <div className="utterance user-utterance">
        <span className="utterance-label">YOU / {String(index + 1).padStart(2, "0")}</span>
        <p data-payload>{turn.user}</p>
      </div>
      <div className="utterance agent-utterance">
        <span className="utterance-label"><Bot aria-hidden="true" /> AGENT / ARCHIVED</span>
        {thinking ? (
          <details className="thinking-block">
            <summary>{originalThinking ? "查看思维链" : "查看公开工作过程"}</summary>
            <pre data-payload>{thinking}</pre>
          </details>
        ) : null}
        {turn.process.length ? (
          <ol className="process-list">
            {turn.process.map((step, stepIndex) => <li data-payload key={`${stepIndex}-${step}`}>{step}</li>)}
          </ol>
        ) : null}
        <div className="final-copy" data-payload>{turn.final || turn.last_observation_summary || "本回合没有可展示的最终内容。"}</div>
        <span className="terminal-meta">
          {turn.status === "completed" ? <CheckCircle2 aria-hidden="true" /> : <CircleAlert aria-hidden="true" />}
          {turn.status} / {turn.terminal_reason || "complete"}
        </span>
      </div>
    </section>
  );
}

function processDescription(event: ChatEvent) {
  switch (event.event) {
    case "action_parsed":
      return `已解析 ${event.action}`;
    case "tool_start":
      return `正在执行 ${event.action}`;
    case "observation":
      return event.summary || `${event.action} 返回 ${event.status}`;
    case "approval_required":
      return `${event.action} 等待审批`;
    case "approval_granted":
      return `${event.action} 已批准`;
    case "approval_denied":
      return `${event.action} 已拒绝`;
    case "approval_timed_out":
      return `${event.action} 审批超时`;
    default:
      return event.event;
  }
}

function ApprovalCard({
  event,
  busy,
  onDecision,
}: {
  event: Extract<ChatEvent, { event: "approval_required" }>;
  busy: boolean;
  onDecision: (approved: boolean) => void;
}) {
  const initialSeconds = Math.max(0, 300 - Math.floor(event.elapsed_ms / 1000));
  const [seconds, setSeconds] = useState(initialSeconds);

  useEffect(() => {
    const timer = window.setInterval(() => setSeconds((value) => Math.max(0, value - 1)), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <section className="approval-card" aria-label="操作审批" aria-live="assertive">
      <div className="approval-heading">
        <TriangleAlert aria-hidden="true" />
        <div>
          <span>HUMAN GATE</span>
          <h3>批准前请核对真实影响</h3>
        </div>
        <time><Clock3 aria-hidden="true" /> {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}</time>
      </div>
      <p data-payload>{event.reason}</p>
      <dl className="approval-details">
        <div><dt>Action</dt><dd data-payload>{event.action}</dd></div>
        <div><dt>Intent</dt><dd data-payload>{event.message}</dd></div>
      </dl>
      <pre data-payload>{JSON.stringify(event.args, null, 2)}</pre>
      <div className="approval-actions">
        <button className="button secondary" disabled={busy || seconds === 0} onClick={() => onDecision(false)}>
          <X aria-hidden="true" /> 拒绝
        </button>
        <button className="button primary" disabled={busy || seconds === 0} onClick={() => onDecision(true)}>
          {busy ? <LoaderCircle className="spin" aria-hidden="true" /> : <Check aria-hidden="true" />} 批准并继续
        </button>
      </div>
    </section>
  );
}

function LiveTurn({
  live,
  pendingUser,
  streamStatus,
  approvalBusy,
  onDecision,
  onRecover,
}: {
  live: ChatState;
  pendingUser: string;
  streamStatus: StreamStatus | null;
  approvalBusy: boolean;
  onDecision: (approved: boolean) => void;
  onRecover: () => void;
}) {
  return (
    <section className="turn live-turn" aria-label="当前回合">
      {pendingUser ? (
        <div className="utterance user-utterance">
          <span className="utterance-label">YOU / LIVE</span>
          <p data-payload>{pendingUser}</p>
        </div>
      ) : null}
      <div className="utterance agent-utterance">
        <span className="utterance-label">
          <Activity aria-hidden="true" /> AGENT / {live.phase.toUpperCase()}
        </span>
        {streamStatus === "retrying" || streamStatus === "recovering" ? (
          <div className="inline-notice" data-tone="warning">
            <WifiOff aria-hidden="true" />
            {streamStatus === "retrying" ? "连接中断，正在重连一次。" : "实时连接不可用，正在读取持久化历史。"}
          </div>
        ) : null}
        {live.notices.map((notice) => (
          <div className="inline-notice" key={notice}><CircleAlert aria-hidden="true" /><span data-payload>{notice}</span></div>
        ))}
        {live.stream.thinking ? (
          <details className="thinking-block" open>
            <summary>模型工作过程</summary>
            <pre data-payload>{live.stream.thinking}</pre>
          </details>
        ) : null}
        {live.stream.content ? <div className="live-copy" data-payload>{live.stream.content}</div> : null}
        {live.stream.args ? (
          <details className="thinking-block">
            <summary>工具参数流</summary>
            <pre data-payload>{live.stream.args}</pre>
          </details>
        ) : null}
        {live.process.length ? (
          <ol className="process-list live-process">
            {live.process.map((event) => (
              <li key={`${event.sequence}-${event.event}`}>
                <Terminal aria-hidden="true" />
                <span data-payload>{processDescription(event)}</span>
              </li>
            ))}
          </ol>
        ) : null}
        {live.approval ? <ApprovalCard event={live.approval} busy={approvalBusy} onDecision={onDecision} /> : null}
        {live.final ? (
          <div className="final-result">
            <span><CheckCircle2 aria-hidden="true" /> FINAL / {live.final.display_status}</span>
            <div className="final-copy" data-payload>{live.final.final || live.final.last_observation_summary}</div>
          </div>
        ) : null}
        {live.error ? (
          <div className="error-result" role="alert">
            <XCircle aria-hidden="true" />
            <div><strong>运行中断</strong><p data-payload>{live.error}</p></div>
            <button className="button secondary" onClick={onRecover}><RefreshCw aria-hidden="true" /> 从历史重建</button>
          </div>
        ) : null}
        {live.phase === "thinking" && !live.stream.thinking ? (
          <span className="thinking-indicator"><LoaderCircle className="spin" aria-hidden="true" /> 正在建立执行路径</span>
        ) : null}
      </div>
    </section>
  );
}

function Composer({
  value,
  disabled,
  onChange,
  onSubmit,
}: {
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
}) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit();
  };
  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    onSubmit();
  };

  useEffect(() => {
    const element = textarea.current;
    if (!element) return;
    element.style.height = "0px";
    element.style.height = `${Math.min(180, Math.max(52, element.scrollHeight))}px`;
  }, [value]);

  return (
    <form className="composer" onSubmit={submit}>
      <div className="composer-index" aria-hidden="true">PROMPT / 01</div>
      <textarea
        ref={textarea}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={keyDown}
        placeholder="描述目标、边界与验收方式"
        aria-label="向 Agent 发送消息"
        disabled={disabled}
        rows={1}
      />
      <button className="send-button" type="submit" disabled={disabled || !value.trim()}>
        {disabled ? <LoaderCircle className="spin" aria-hidden="true" /> : <SendHorizontal aria-hidden="true" />}
        <span>{disabled ? "运行中" : "发送"}</span>
      </button>
      <span className="composer-hint">Enter 发送 / Shift + Enter 换行</span>
    </form>
  );
}

function EmptyStage({ phase }: { phase: ChatPhase }) {
  const copy = PHASE_COPY[phase];
  return (
    <div className="empty-stage">
      <span className="stage-index">00 / NEW RUN</span>
      <div className="stage-title" aria-hidden="true">
        <span>{copy.title.slice(0, Math.ceil(copy.title.length / 2))}</span>
        <span>{copy.title.slice(Math.ceil(copy.title.length / 2))}</span>
      </div>
      <div className="stage-intro">
        <span>{copy.eyebrow}</span>
        <h1>从清晰目标<br />开始。</h1>
        <p>{copy.detail}</p>
      </div>
      <div className="stage-axis" aria-hidden="true"><span>CONTEXT</span><ChevronRight /><span>ACTION</span><ChevronRight /><span>EVIDENCE</span></div>
    </div>
  );
}

function SessionDialog({
  action,
  busy,
  onClose,
  onConfirm,
}: {
  action: SessionAction;
  busy: boolean;
  onClose: () => void;
  onConfirm: (value?: string) => void;
}) {
  const [title, setTitle] = useState(action?.chat.title || "");
  return (
    <Dialog.Root open={Boolean(action)} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="action-dialog">
          <Dialog.Title>{action?.kind === "rename" ? "重命名会话" : "删除会话"}</Dialog.Title>
          <Dialog.Description>
            {action?.kind === "rename" ? "新名称会同步写入本地会话记录。" : "删除后会话记录不可从 Workbench 恢复。"}
          </Dialog.Description>
          {action?.kind === "rename" ? (
            <input value={title} onChange={(event) => setTitle(event.target.value)} autoFocus aria-label="会话名称" />
          ) : (
            <div className="delete-warning"><TriangleAlert aria-hidden="true" /><span data-payload>{action?.chat.title}</span></div>
          )}
          <div className="dialog-actions">
            <button className="button secondary" onClick={onClose}>取消</button>
            <button
              className={`button ${action?.kind === "delete" ? "danger" : "primary"}`}
              disabled={busy || (action?.kind === "rename" && !title.trim())}
              onClick={() => onConfirm(action?.kind === "rename" ? title.trim() : undefined)}
            >
              {busy ? <LoaderCircle className="spin" aria-hidden="true" /> : action?.kind === "delete" ? <Trash2 aria-hidden="true" /> : <Check aria-hidden="true" />}
              {action?.kind === "delete" ? "确认删除" : "保存名称"}
            </button>
          </div>
          <Dialog.Close asChild><IconButton label="关闭" className="dialog-close"><X aria-hidden="true" /></IconButton></Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function App() {
  const reducedMotion = useReducedMotion();
  const { theme, resolvedMode } = useTheme();
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(() => sessionFromHash());
  const [chat, setChat] = useState<ChatPayload | null>(null);
  const [loadingChat, setLoadingChat] = useState(Boolean(sessionId));
  const [activeJob, setActiveJob] = useState<ActiveJob | null>(() => readActiveJob());
  const [live, setLive] = useState<ChatState>(initialChatState);
  const [streamStatus, setStreamStatus] = useState<StreamStatus | null>(null);
  const [pendingUser, setPendingUser] = useState("");
  const [message, setMessage] = useState("");
  const [filter, setFilter] = useState("");
  const [railOpen, setRailOpen] = useState(true);
  const [railWidth, setRailWidth] = useState(326);
  const [mobileSessions, setMobileSessions] = useState(false);
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [canvasEnabled, setCanvasEnabled] = useState(true);
  const workspaceOpenerRef = useRef<HTMLButtonElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [sessionAction, setSessionAction] = useState<SessionAction>(null);
  const [sessionActionBusy, setSessionActionBusy] = useState(false);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const railResizeRef = useRef<{ pointerId: number; startX: number; startWidth: number } | null>(null);
  // Preserve the raw streamed thinking per run so a finished turn can still expand it,
  // instead of only the backend's rebuilt "public work log".
  const [thinkingCache, setThinkingCache] = useState<Record<string, string>>({});
  const streamThinkingRef = useRef("");
  const stickToBottomRef = useRef(true);

  const refreshChats = useCallback(async () => {
    const payload = await api.listChats();
    setChats(payload.chats);
  }, []);

  // Remember which button opened the workspace so focus can return to it on close.
  const openWorkspace = useCallback((event: React.MouseEvent<HTMLButtonElement>) => {
    workspaceOpenerRef.current = event.currentTarget;
    setWorkspaceOpen(true);
  }, []);

  // Global refresh for the workspace panel's 10s tick and manual refresh; best-effort.
  const refreshGlobal = useCallback(async () => {
    try {
      const [healthPayload, chatsPayload] = await Promise.all([api.getHealth(), api.listChats()]);
      setHealth(healthPayload);
      setChats(chatsPayload.chats);
    } catch {
      // keep the last snapshot on error.
    }
  }, []);

  const loadChat = useCallback(async (id: string) => {
    if (sessionFromHash() !== id) return;
    setLoadingChat(true);
    try {
      const payload = await api.getChat(id);
      if (sessionFromHash() !== id) return;
      setChat(payload);
      setError(null);
    } catch (nextError) {
      if (sessionFromHash() !== id) return;
      setChat(null);
      setError(displayError(nextError));
    } finally {
      if (sessionFromHash() === id) setLoadingChat(false);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    void Promise.all([api.getHealth(), api.listChats()])
      .then(([healthPayload, chatsPayload]) => {
        if (!alive) return;
        setHealth(healthPayload);
        setChats(chatsPayload.chats);
      })
      .catch((nextError) => alive && setError(displayError(nextError)));
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    const updateRoute = () => setSessionId(sessionFromHash());
    addEventListener("hashchange", updateRoute);
    if (!location.hash && activeJob) setSessionHash(activeJob.sessionId);
    else if (!location.hash) setSessionHash(null);
    return () => removeEventListener("hashchange", updateRoute);
  }, [activeJob]);

  useEffect(() => {
    if (!sessionId) return;
    let alive = true;
    void api.getChat(sessionId)
      .then((payload) => {
        if (!alive) return;
        setChat(payload);
        setError(null);
      })
      .catch((nextError) => {
        if (!alive) return;
        setChat(null);
        setError(displayError(nextError));
      })
      .finally(() => alive && setLoadingChat(false));
    return () => { alive = false; };
  }, [sessionId]);

  useEffect(() => {
    if (!activeJob) return;
    const settleJob = async () => {
      try {
        await Promise.all([loadChat(activeJob.sessionId), refreshChats()]);
      } catch (nextError) {
        setError(displayError(nextError));
      } finally {
        sessionStorage.removeItem(ACTIVE_JOB_KEY);
        setActiveJob((current) => current?.jobId === activeJob.jobId ? null : current);
        setPendingUser("");
        setLive(initialChatState);
      }
    };
    const stop = subscribeChatJob({
      jobId: activeJob.jobId,
      sessionId: activeJob.sessionId,
      onStatus: setStreamStatus,
      onEvent(event) {
        if (event.event === "chat_started") streamThinkingRef.current = "";
        else if (event.event === "model_stream_chunk" && event.kind === "thinking") {
          streamThinkingRef.current += event.text;
        }
        setLive((state) => chatReducer(state, event));
        if (event.event !== "final" && event.event !== "error") return;
        if (event.event === "final" && streamThinkingRef.current && event.run_id) {
          const captured = streamThinkingRef.current;
          setThinkingCache((cache) => ({ ...cache, [event.run_id]: captured }));
        }
        streamThinkingRef.current = "";
        void settleJob();
      },
      onRecover(id) {
        setLive(recoveringState);
        if (id === activeJob.sessionId) void settleJob();
      },
    });
    return stop;
  }, [activeJob, loadChat, refreshChats]);

  // Follow new content while the user is parked at the bottom; stop nagging once they scroll up.
  const handleTranscriptScroll = useCallback(() => {
    const element = transcriptRef.current;
    if (!element) return;
    stickToBottomRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80;
  }, []);

  useEffect(() => {
    const element = transcriptRef.current;
    if (!element || !stickToBottomRef.current) return;
    element.scrollTo({ top: element.scrollHeight, behavior: reducedMotion ? "auto" : "smooth" });
  }, [chat, live, pendingUser, reducedMotion]);

  const newSession = () => {
    setSessionHash(null);
    setSessionId(null);
    setChat(null);
    setLive(initialChatState);
    setPendingUser("");
    setMessage("");
    setError(null);
    setMobileSessions(false);
  };

  const selectSession = (id: string) => {
    setLoadingChat(true);
    setSessionHash(id);
    setMobileSessions(false);
    setLive(initialChatState);
    setPendingUser("");
  };

  const send = async () => {
    const text = message.trim();
    if (!text || activeJob) return;
    setError(null);
    setPendingUser(text);
    setMessage("");
    setLive({ ...initialChatState, phase: "thinking" });
    try {
      const started = await api.startChat(text, sessionId || undefined);
      const next = { jobId: started.job_id, sessionId: started.session_id };
      sessionStorage.setItem(ACTIVE_JOB_KEY, JSON.stringify(next));
      setActiveJob(next);
      setSessionHash(next.sessionId);
      setSessionId(next.sessionId);
    } catch (nextError) {
      setPendingUser("");
      setLive({ ...initialChatState, phase: "error", error: displayError(nextError) });
    }
  };

  const decideApproval = async (approved: boolean) => {
    if (!activeJob) return;
    setApprovalBusy(true);
    try {
      await api.decideApproval(activeJob.jobId, approved);
    } catch (nextError) {
      setError(displayError(nextError));
    } finally {
      setApprovalBusy(false);
    }
  };

  const recover = async () => {
    if (!sessionId) return;
    setLive(recoveringState);
    await loadChat(sessionId);
    setLive(initialChatState);
  };

  const confirmSessionAction = async (value?: string) => {
    if (!sessionAction) return;
    setSessionActionBusy(true);
    try {
      if (sessionAction.kind === "rename") {
        const renamed = await api.renameChat(sessionAction.chat.session_id, value || "");
        if (chat?.session_id === sessionAction.chat.session_id) setChat({ ...chat, title: renamed.title });
      } else {
        await api.deleteChat(sessionAction.chat.session_id);
        if (sessionId === sessionAction.chat.session_id) newSession();
      }
      setSessionAction(null);
      await refreshChats();
    } catch (nextError) {
      setError(displayError(nextError));
    } finally {
      setSessionActionBusy(false);
    }
  };

  const startRailResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    railResizeRef.current = { pointerId: event.pointerId, startX: event.clientX, startWidth: railWidth };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const moveRailResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = railResizeRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    setRailWidth(Math.min(420, Math.max(260, drag.startWidth + event.clientX - drag.startX)));
  };

  const stopRailResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (railResizeRef.current?.pointerId !== event.pointerId) return;
    railResizeRef.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  };

  const keyRailResize = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      setRailWidth((width) => Math.min(420, Math.max(260, width + (event.key === "ArrowRight" ? 16 : -16))));
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      setRailWidth(event.key === "Home" ? 260 : 420);
    }
  };

  const phase = activeJob && activeJob.sessionId !== sessionId ? "idle" : live.phase;
  const showLive = live.phase !== "idle" && (!activeJob || activeJob.sessionId === sessionId);
  const hasTranscript = Boolean(chat?.turns.length || showLive || pendingUser);
  const spring = reducedMotion ? { duration: 0 } : { type: "spring" as const, stiffness: 320, damping: 32, mass: 0.8 };

  const sessionPanel = (
    <SessionPanel
      chats={chats}
      selectedId={sessionId}
      expanded
      filter={filter}
      onFilter={setFilter}
      onNew={newSession}
      onSelect={selectSession}
      onAction={setSessionAction}
    />
  );

  return (
    <Tooltip.Provider delayDuration={350}>
      <div className="app-shell" data-phase={phase}>
        <ContextField phase={phase} themeKey={`${theme}-${resolvedMode}`} enabled={canvasEnabled} />
        <CommandSpine health={health} onOpenSessions={() => setMobileSessions(true)} onOpenWorkspace={openWorkspace} canvasEnabled={canvasEnabled} onToggleCanvas={() => setCanvasEnabled((value) => !value)} />

        <motion.aside className="session-rail desktop-only" data-expanded={railOpen} animate={{ width: railOpen ? railWidth : 76 }} transition={spring}>
          <div className="rail-cap">
            {railOpen ? <span>SESSIONS / {String(chats.length).padStart(2, "0")}</span> : <span aria-hidden="true">S</span>}
            <IconButton label={railOpen ? "收起会话轨道" : "展开会话轨道"} onClick={() => setRailOpen((value) => !value)}>
              {railOpen ? <PanelLeftClose aria-hidden="true" /> : <PanelLeftOpen aria-hidden="true" />}
            </IconButton>
          </div>
          <SessionPanel
            chats={chats}
            selectedId={sessionId}
            expanded={railOpen}
            filter={filter}
            onFilter={setFilter}
            onNew={newSession}
            onSelect={selectSession}
            onAction={setSessionAction}
          />
          <div className="rail-footer"><Wifi aria-hidden="true" />{railOpen && <span>LOCAL / CONNECTED</span>}</div>
          <div
            className="rail-resizer"
            role="separator"
            aria-label="调整会话轨道宽度"
            aria-orientation="vertical"
            aria-valuemin={260}
            aria-valuemax={420}
            aria-valuenow={Math.round(railWidth)}
            tabIndex={0}
            onPointerDown={startRailResize}
            onPointerMove={moveRailResize}
            onPointerUp={stopRailResize}
            onPointerCancel={stopRailResize}
            onKeyDown={keyRailResize}
          />
        </motion.aside>

        <main className="chat-stage" style={{ "--rail-width": railOpen ? `${railWidth}px` : "76px" } as React.CSSProperties}>
          <div className="stage-header">
            <div>
              <span>{sessionId ? "ACTIVE SESSION" : "UNBOUND SESSION"}</span>
              <h2 data-payload>{chat?.title || "New task"}</h2>
            </div>
            {sessionId ? <code>{sessionId.slice(0, 8)}</code> : <code>LOCAL / DRAFT</code>}
          </div>

          {error ? (
            <div className="global-error" role="alert">
              <CircleAlert aria-hidden="true" /><span>{error}</span>
              <IconButton label="关闭错误" onClick={() => setError(null)}><X aria-hidden="true" /></IconButton>
            </div>
          ) : null}

          <div className="transcript" ref={transcriptRef} aria-busy={loadingChat} onScroll={handleTranscriptScroll}>
            {loadingChat ? <div className="loading-state"><LoaderCircle className="spin" aria-hidden="true" /> 正在读取会话历史</div> : null}
            {!loadingChat && !hasTranscript ? <EmptyStage phase={phase} /> : null}
            {chat?.turns.map((turn, index) => (
              <div key={turn.run_id || index}>
                <HistoryTurn turn={turn} index={index} originalThinking={thinkingCache[turn.run_id]} />
              </div>
            ))}
            {showLive || pendingUser ? (
              <LiveTurn
                live={live}
                pendingUser={pendingUser}
                streamStatus={streamStatus}
                approvalBusy={approvalBusy}
                onDecision={decideApproval}
                onRecover={recover}
              />
            ) : null}
          </div>

          <Composer value={message} disabled={Boolean(activeJob)} onChange={setMessage} onSubmit={send} />
        </main>

        <button
          type="button"
          className="workspace-reveal desktop-only"
          aria-label="打开工作台"
          onClick={openWorkspace}
        >
          <PanelRightOpen aria-hidden="true" />
          <span>WORKSPACE</span>
        </button>

        <WorkspacePanel
          open={workspaceOpen}
          onOpenChange={setWorkspaceOpen}
          health={health}
          chats={chats}
          onGlobalRefresh={refreshGlobal}
          openerRef={workspaceOpenerRef}
        />

        <Dialog.Root open={mobileSessions} onOpenChange={setMobileSessions}>
          <Dialog.Portal>
            <Dialog.Overlay className="dialog-overlay" />
            <Dialog.Content className="mobile-sheet">
              <div className="mobile-sheet-head">
                <Dialog.Title>会话</Dialog.Title>
                <Dialog.Close asChild><IconButton label="关闭会话"><X aria-hidden="true" /></IconButton></Dialog.Close>
              </div>
              {sessionPanel}
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>

        <SessionDialog
          key={sessionAction ? `${sessionAction.kind}-${sessionAction.chat.session_id}` : "closed"}
          action={sessionAction}
          busy={sessionActionBusy}
          onClose={() => setSessionAction(null)}
          onConfirm={confirmSessionAction}
        />
      </div>
    </Tooltip.Provider>
  );
}
