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
  Square,
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
  useId,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { ContextField } from "./ContextField";
import { CommandPalette, type PaletteCommand } from "./CommandPalette";
import { api, ApiError } from "./api/client";
import { isTerminalChatEvent, subscribeChatJob, type StreamStatus } from "./api/sse";
import type { ChatEvent, ChatPayload, ChatSummary, ChatTurn, HealthPayload } from "./api/types";
import { chatReducer, initialChatState, recoveringState, type ChatPhase, type ChatState } from "./chat/state";
import { Orb, resolveChatOrbState } from "./Orb";
import { loadLayout, saveLayout, type WorkspaceView } from "./layout";
import { useTheme, type ModePreference, type ThemeName } from "./theme";
import { WorkspacePanel, type WorkspacePanelHandle } from "./workspace/WorkspacePanel";

const ACTIVE_JOB_KEY = "agent.frontend.active-job";
const RESUMABLE_REASONS = new Set(["cancelled", "timed_out", "interrupted", "failed"]);

interface ActiveJob {
  jobId: string;
  sessionId: string;
}

type SessionAction = { kind: "rename" | "delete"; chat: ChatSummary } | null;

const PHASE_COPY: Record<ChatPhase, string> = {
  idle: "准备就绪", thinking: "正在思考", stream: "正在生成", tool: "执行工具",
  approval: "等待审批", final: "已完成", error: "运行中断", recovering: "恢复历史",
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
        <Orb state="connecting" /> 连接中
      </span>
    );
  }
  const ready = !health.api_key_required || health.api_key_present;
  return (
    <span className="command-status" data-tone={ready ? "ok" : "warning"}>
      {ready ? <KeyRound aria-hidden="true" /> : <TriangleAlert aria-hidden="true" />}
      {ready ? "密钥就绪" : "缺少密钥"}
    </span>
  );
}

function CommandSpine({
  health,
  onOpenSessions,
  onOpenWorkspace,
  canvasEnabled,
  onToggleCanvas,
  commands,
  onCommandPaletteOpenChange,
}: {
  health: HealthPayload | null;
  onOpenSessions: () => void;
  onOpenWorkspace: (event: React.MouseEvent<HTMLButtonElement>) => void;
  canvasEnabled: boolean;
  onToggleCanvas: () => void;
  commands: PaletteCommand[];
  onCommandPaletteOpenChange: (open: boolean) => void;
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
        <CommandPalette commands={commands} onOpenChange={onCommandPaletteOpenChange} />
        <span>Workbench</span>
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
        <span className="utterance-label">你</span>
        <p data-payload>{turn.user}</p>
      </div>
      <div className="utterance agent-utterance">
        <span className="utterance-label"><Bot aria-hidden="true" /> Agent</span>
        {thinking ? (
          <details className="thinking-block">
            <summary>{originalThinking ? "查看思维链" : "查看公开工作过程"}</summary>
            <pre data-payload>{thinking}</pre>
          </details>
        ) : null}
        {turn.process.length ? (
          <details className="thinking-block activity-history"><summary>执行记录 · {turn.process.length}</summary><ol className="process-list">
            {turn.process.map((step, stepIndex) => <li data-payload key={`${stepIndex}-${step}`}>{step}</li>)}
          </ol></details>
        ) : null}
        <div className="final-copy" data-payload>{turn.final || "本回合没有最终回答。"}</div>
        {turn.last_observation_summary ? <details className="thinking-block"><summary>观察摘要</summary><pre data-payload>{turn.last_observation_summary}</pre></details> : null}
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
    case "chat_started":
      return "回合已开始";
    case "model_call_start":
      return "正在请求模型";
    case "model_stream_start":
      return "模型流已开始";
    case "model_stream_chunk":
      return event.text;
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
  // 服务端在 approval_required 事件上携带权威审批窗口；字段缺失时退回 300 秒。
  const expiresInMs = "expires_in_ms" in event && typeof event.expires_in_ms === "number"
    ? event.expires_in_ms
    : 300_000;
  const [seconds, setSeconds] = useState(() => Math.max(0, Math.floor(expiresInMs / 1000)));

  useEffect(() => {
    const timer = window.setInterval(() => setSeconds((value) => Math.max(0, value - 1)), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <section className="approval-card" aria-label="操作审批" aria-live="assertive">
      <div className="approval-heading">
        <TriangleAlert aria-hidden="true" />
        <div>
          <span>需要你的决定</span>
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
      {seconds === 0 ? (
        <div className="inline-notice" data-tone="warning">
          <Clock3 aria-hidden="true" />
          <span>审批可能已超时，仍可提交决定，以服务端结果为准。</span>
        </div>
      ) : null}
      <div className="approval-actions">
        <button className="button secondary" disabled={busy} onClick={() => onDecision(false)}>
          <X aria-hidden="true" /> 拒绝
        </button>
        <button className="button primary" disabled={busy} onClick={() => onDecision(true)}>
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
  // One orb for the whole turn: the label already renders for every phase, so a
  // single indicator here covers all of them without stacking canvases.
  const orbState = resolveChatOrbState(live.phase, live.lastAction, live.streamKind);
  const [phaseDetailsOpen, setPhaseDetailsOpen] = useState(false);
  const phaseDetailsId = useId();
  return (
    <section className="turn live-turn" aria-label="当前回合">
      {pendingUser ? (
        <div className="utterance user-utterance">
          <span className="utterance-label">你</span>
          <p data-payload>{pendingUser}</p>
        </div>
      ) : null}
      <div className="utterance agent-utterance">
        <span className="utterance-label phase-status">
          {orbState ? (
            <button className="phase-toggle" type="button" aria-label="阶段详情"
              aria-expanded={phaseDetailsOpen} aria-controls={phaseDetailsId}
              onClick={() => setPhaseDetailsOpen((open) => !open)}>
              <Orb state={orbState} />
              <span>{PHASE_COPY[live.phase]}</span>
              <ChevronRight className="phase-chevron" aria-hidden="true" />
            </button>
          ) : <><Activity aria-hidden="true" /> {PHASE_COPY[live.phase]}</>}
          {orbState && live.phaseEvent ? <span className="phase-activity" data-payload>{processDescription(live.phaseEvent)}</span> : null}
        </span>
        {orbState ? (
          <section id={phaseDetailsId} className="thinking-block phase-details" aria-label="阶段详情" hidden={!phaseDetailsOpen}>
            <pre data-payload>{`当前状态：${live.phase} / ${orbState}\n事件类型：${live.phaseEvent?.event ?? "暂无（本地状态）"}\n最近活动：${live.phaseEvent ? processDescription(live.phaseEvent) : live.phase === "recovering" ? "正在读取持久化历史" : "等待服务端事件"}`}</pre>
          </section>
        ) : null}
        {streamStatus === "retrying" || streamStatus === "recovering" ? (
          <div className="inline-notice" data-tone="warning">
            {streamStatus === "retrying" ? <Orb state="connecting" /> : <WifiOff aria-hidden="true" />}
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
        {live.approval ? (
          <ApprovalCard key={live.approval.sequence} event={live.approval} busy={approvalBusy} onDecision={onDecision} />
        ) : null}
        {live.final ? (
          <div className="final-result">
            <span><CheckCircle2 aria-hidden="true" /> 执行结果 · {live.final.display_status}</span>
            <div className="final-copy" data-payload>{live.final.final || "本回合没有最终回答。"}</div>
            {live.final.last_observation_summary ? <details className="thinking-block"><summary>观察摘要</summary><pre data-payload>{live.final.last_observation_summary}</pre></details> : null}
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
          // The label orb above already carries the pending signal; a second
          // spinner on the same turn would just be noise.
          <span className="thinking-indicator">正在建立执行路径</span>
        ) : null}
      </div>
    </section>
  );
}

function Composer({
  value,
  disabled,
  stopping,
  onChange,
  onSubmit,
  onStop,
}: {
  value: string;
  disabled: boolean;
  stopping: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
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
      <button
        className="send-button"
        type={disabled ? "button" : "submit"}
        data-action={disabled ? "stop" : "send"}
        disabled={disabled ? stopping : !value.trim()}
        onClick={disabled ? onStop : undefined}
        aria-label={disabled ? (stopping ? "正在停止当前任务" : "停止当前任务") : "发送"}
      >
        {disabled
          ? stopping ? <LoaderCircle className="spin" aria-hidden="true" /> : <Square aria-hidden="true" />
          : <SendHorizontal aria-hidden="true" />}
        <span>{disabled ? (stopping ? "正在停止" : "停止") : "发送"}</span>
      </button>
      <span className="composer-hint">Enter 发送 / Shift + Enter 换行</span>
    </form>
  );
}

function EmptyStage({ phase }: { phase: ChatPhase }) {
  return (
    <div className="empty-stage">
      <div className="stage-intro">
        <span><Bot aria-hidden="true" /> {PHASE_COPY[phase]}</span>
        <h1>今天，一起完成什么？</h1>
        <p>描述目标，或从一个问题开始。<br />执行过程、需要确认的操作和结果，都会留在这里。</p>
      </div>
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
  const [layout, setLayout] = useState(loadLayout);
  const [mobileSessions, setMobileSessions] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const { railOpen, railWidth, canvasEnabled, workspaceView } = layout;
  const [workspaceOpener, setWorkspaceOpener] = useState<HTMLButtonElement | null>(null);
  const workspaceRef = useRef<WorkspacePanelHandle>(null);
  const [error, setError] = useState<string | null>(null);
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [cancelBusy, setCancelBusy] = useState(false);
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

  useEffect(() => saveLayout(layout), [layout]);

  const requestWorkspaceView = useCallback((view: WorkspaceView) => {
    workspaceRef.current?.requestView(view);
  }, []);

  const showWorkspace = useCallback((opener: HTMLButtonElement | null, view?: WorkspaceView) => {
    if (opener) setWorkspaceOpener(opener);
    if (view) {
      if (workspaceOpen) requestWorkspaceView(view);
      else setLayout((current) => ({ ...current, workspaceView: view }));
    }
    setWorkspaceOpen(true);
  }, [requestWorkspaceView, workspaceOpen]);

  // Remember which button opened the workspace so focus can return to it on close.
  const openWorkspace = useCallback((event: React.MouseEvent<HTMLButtonElement>) => {
    showWorkspace(event.currentTarget);
  }, [showWorkspace]);

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
        setApprovalBusy(false);
        setCancelBusy(false);
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
        if (!isTerminalChatEvent(event)) return;
        if (streamThinkingRef.current && "run_id" in event && event.run_id) {
          const captured = streamThinkingRef.current;
          setThinkingCache((cache) => ({ ...cache, [event.run_id]: captured }));
        }
        streamThinkingRef.current = "";
        void settleJob();
      },
      onRecover(id) {
        setLive(recoveringState);
        if (id === activeJob.sessionId) void loadChat(id);
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
      const previous = chat?.session_id === sessionId ? chat.turns.at(-1) : undefined;
      const resumeJobId = previous?.job_id && RESUMABLE_REASONS.has(previous.terminal_reason)
        ? previous.job_id
        : null;
      const started = resumeJobId
        ? await api.resumeChat(resumeJobId, text)
        : await api.startChat(text, sessionId || undefined);
      const next = { jobId: started.job_id, sessionId: started.session_id };
      sessionStorage.setItem(ACTIVE_JOB_KEY, JSON.stringify(next));
      setActiveJob(next);
      setCancelBusy(false);
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

  const cancelActiveJob = async () => {
    if (!activeJob || cancelBusy) return;
    setCancelBusy(true);
    try {
      await api.cancelChat(activeJob.jobId);
    } catch (nextError) {
      setCancelBusy(false);
      setError(displayError(nextError));
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
    const width = Math.min(420, Math.max(260, drag.startWidth + event.clientX - drag.startX));
    setLayout((current) => ({ ...current, railWidth: width }));
  };

  const stopRailResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (railResizeRef.current?.pointerId !== event.pointerId) return;
    railResizeRef.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  };

  const keyRailResize = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      setLayout((current) => ({
        ...current,
        railWidth: Math.min(420, Math.max(260, current.railWidth + (event.key === "ArrowRight" ? 16 : -16))),
      }));
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      setLayout((current) => ({ ...current, railWidth: event.key === "Home" ? 260 : 420 }));
    }
  };

  const phase = activeJob && activeJob.sessionId !== sessionId ? "idle" : live.phase;
  const showLive = live.phase !== "idle" && (!activeJob || activeJob.sessionId === sessionId);
  const hasTranscript = Boolean(chat?.turns.length || showLive || pendingUser);
  const spring = reducedMotion ? { duration: 0 } : { type: "spring" as const, stiffness: 320, damping: 32, mass: 0.8 };
  const paletteCommands: PaletteCommand[] = [
    { id: "new", label: "新建任务", detail: "回到空白会话", keywords: ["new", "chat"], run: () => newSession() },
    ...(["files", "git", "terminal", "runs", "system"] as WorkspaceView[]).map((view) => ({
      id: `workspace-${view}`,
      label: `打开 ${view[0].toUpperCase()}${view.slice(1)}`,
      detail: "打开工作台并切换到该视图",
      keywords: ["workspace", "工作台", view],
      // command.run executes only after a palette action, never during render.
      // eslint-disable-next-line react-hooks/refs
      run: (opener: HTMLButtonElement | null) => showWorkspace(opener, view),
    })),
    { id: "refresh", label: "刷新状态与会话", detail: "重新读取健康状态和会话索引", keywords: ["refresh", "reload"], run: () => void refreshGlobal() },
    {
      id: "rail",
      label: railOpen ? "收起会话轨道" : "展开会话轨道",
      detail: "切换桌面会话导航",
      keywords: ["rail", "sessions", "layout"],
      run: () => setLayout((current) => ({ ...current, railOpen: !current.railOpen })),
    },
    {
      id: "canvas",
      label: canvasEnabled ? "隐藏上下文画布" : "显示上下文画布",
      detail: "切换背景上下文动画",
      keywords: ["canvas", "context", "layout"],
      run: () => setLayout((current) => ({ ...current, canvasEnabled: !current.canvasEnabled })),
    },
  ];

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
      <div className="app-shell" data-phase={phase} data-workspace-open={workspaceOpen}>
        <ContextField phase={phase} themeKey={`${theme}-${resolvedMode}`} enabled={canvasEnabled && !hasTranscript && !showLive && !pendingUser} />
        <CommandSpine
          health={health}
          onOpenSessions={() => setMobileSessions(true)}
          onOpenWorkspace={openWorkspace}
          canvasEnabled={canvasEnabled}
          onToggleCanvas={() => setLayout((current) => ({ ...current, canvasEnabled: !current.canvasEnabled }))}
          commands={paletteCommands}
          onCommandPaletteOpenChange={setCommandPaletteOpen}
        />

        <motion.aside className="session-rail desktop-only" data-expanded={railOpen} animate={{ width: railOpen ? railWidth : 76 }} transition={spring}>
          <div className="rail-cap">
            {railOpen ? <span>会话 <span className="rail-count">{chats.length}</span></span> : <span aria-hidden="true">A</span>}
            <IconButton label={railOpen ? "收起会话轨道" : "展开会话轨道"} onClick={() => setLayout((current) => ({ ...current, railOpen: !current.railOpen }))}>
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
          <div className="rail-footer"><Wifi aria-hidden="true" />{railOpen && <span>本地工作区</span>}</div>
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
              <h2 data-payload>{chat?.title || "新任务"}</h2>
            </div>
            <span className="stage-state">{PHASE_COPY[phase]}</span>
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

          <Composer
            value={message}
            disabled={Boolean(activeJob)}
            stopping={cancelBusy}
            onChange={setMessage}
            onSubmit={send}
            onStop={cancelActiveJob}
          />
        </main>

        <button
          type="button"
          className="workspace-reveal desktop-only"
          aria-label="打开工作台"
          onClick={openWorkspace}
        >
          <PanelRightOpen aria-hidden="true" />
          <span>工作台</span>
        </button>

        <WorkspacePanel
          ref={workspaceRef}
          open={workspaceOpen}
          onOpenChange={setWorkspaceOpen}
          health={health}
          chats={chats}
          onGlobalRefresh={refreshGlobal}
          opener={workspaceOpener}
          onOpenSession={selectSession}
          view={workspaceView}
          onViewChange={(view) => setLayout((current) => ({ ...current, workspaceView: view }))}
          deferModal={commandPaletteOpen || mobileSessions || Boolean(sessionAction)}
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
