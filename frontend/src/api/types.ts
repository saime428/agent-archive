export interface SettingsReadiness {
  mode: string;
  status: string;
  provider: string;
  model: string;
  base_url: string;
  api_key_env: string | null;
  api_key_present: boolean;
  api_key_required: boolean;
  native_tools: boolean;
  loaded_files: string[];
  warnings: string[];
  checks: string[];
}

export interface WorkspaceRisk {
  mode: string;
  risk_level: string;
  summary: string;
  signals: { uncommitted_files: number; failed_runs: number; snapshots: number };
  uncommitted_files: string[];
  checks: string[];
}

// memory_review 的候选/生效项结构在 SettingsView 用到时细化；此处只固定 mode 只读契约。
export interface MemoryReview {
  mode: string;
  [key: string]: unknown;
}

export interface HealthPayload {
  status: string;
  app: string;
  workspace: string;
  provider: string;
  model: string;
  mode: string;
  deepseek_api_key_env: string;
  deepseek_api_key_present: boolean;
  base_url: string;
  api_key_env: string | null;
  api_key_present: boolean;
  api_key_required: boolean;
  native_tools: boolean;
  provider_notice: string;
  settings_readiness: SettingsReadiness;
  workspace_risk: WorkspaceRisk;
  memory_review: MemoryReview;
}

export interface FileEntry {
  name: string;
  path: string;
  kind: "dir" | "file";
  size: number | null;
}

export interface FilesPayload {
  path: string;
  entries: FileEntry[];
}

export interface FilePayload {
  path: string;
  content: string;
  truncated: boolean;
  size: number;
}

export interface SaveFilePayload {
  status: "ok";
  run_id: string;
  path: string;
  bytes_written: number;
  snapshot_path: string;
  restore_hint: string;
}

export interface DiffPayload {
  path: string;
  snapshot_path: string;
  diff: string;
  truncated: boolean;
  current_exists: boolean;
  snapshot_missing: boolean;
}

export interface RestorePayload {
  status: "ok";
  action: "restored" | "deleted";
  path: string;
  snapshot_path: string;
}

export interface RunListItem {
  run_id: string;
  status: string;
  risk_level: string;
  created_at: string;
  updated_at: string;
  run_dir: string;
  summary_path: string;
  tool_calls_path: string;
}

export interface RunsPayload {
  workspace: string;
  runs: RunListItem[];
}

export interface ReviewInfo {
  latest_action: string;
  last_observation_summary: string;
  changed_files: string[];
  snapshot_count: number;
  manual_checks: string[];
}

export interface WorkflowInfo {
  mode: string;
  verification_commands: string[];
  review_steps: string[];
}

export interface FailureInfo {
  status: string;
  failure_count: number;
  latest_failure: Record<string, unknown> | null;
  next_checks: string[];
}

export interface PatchReviewInfo {
  mode: string;
  risk_level: string;
  summary: string;
  checks: string[];
  verification_commands: string[];
  next_action: string;
}

export interface RecoveryInfo {
  mode: string;
  status: string;
  rollback_available: boolean;
  summary: string;
  latest_failure: Record<string, unknown> | null;
  steps: string[];
  checks: string[];
  verification_commands: string[];
  next_action: string;
}

export interface ReplayStep {
  line_number: number;
  phase: string;
  action: string;
  status: string;
  summary: string;
  terminal: boolean;
  policy_decision: string;
}

export interface ReplayInfo {
  mode: string;
  step_count: number;
  steps: ReplayStep[];
}

export interface RunSnapshot {
  path: string;
  snapshot_path: string;
  [key: string]: unknown;
}

export interface ToolCall {
  line_number: number;
  valid: boolean;
  raw: string;
  data: unknown;
  error: string | null;
}

export interface RunDetailPayload {
  run_id: string;
  run_dir: string;
  summary: string;
  tool_calls: ToolCall[];
  snapshots: RunSnapshot[];
  review: ReviewInfo;
  workflow: WorkflowInfo;
  failure: FailureInfo;
  patch_review: PatchReviewInfo;
  recovery: RecoveryInfo;
  replay: ReplayInfo;
}

// AgentConfig 全键；写入白名单只是其中一部分（SettingsView 强制）。
export interface AgentConfigRecord {
  provider: string;
  model: string;
  mode: string;
  sandbox: string;
  approval: string;
  dry_run: boolean;
  web_search_enabled: boolean;
  computer_read_enabled: boolean;
  native_tools: boolean;
  default_skills: string[];
  allowed_commands: string[];
  base_url: string;
  deepseek_api_key_env: string;
  api_key_env: string;
  enabled_hooks: string[];
  blocking_hooks: string[];
  memory_auto_write: boolean;
  memory_max_items: number;
  max_consecutive_errors: number;
}

export interface ConfigDiagnostics {
  global_config_path: string;
  project_config_path: string;
  loaded_files: string[];
  warnings: string[];
}

export interface ConfigPayload {
  workspace: string;
  config: AgentConfigRecord;
  diagnostics: ConfigDiagnostics;
  status?: "ok";
}

// 浏览器写入白名单：与后端 _validated_config_updates 一致的可写键子集。
export interface ConfigUpdates {
  provider: string;
  model: string;
  mode: string;
  sandbox: string;
  approval: string;
  dry_run: boolean;
  web_search_enabled: boolean;
  computer_read_enabled: boolean;
  native_tools: boolean;
  default_skills: string[];
}

export interface ToolInfo {
  name: string;
  category: string;
  dry_run: string;
  description: string;
}

export interface ToolsPayload {
  tools: ToolInfo[];
}

export interface ChatSummary {
  session_id: string;
  created_at: string;
  updated_at: string;
  turn_count: number;
  title: string;
  latest_user: string;
  latest_final: string;
  status: string;
}

export interface ChatTurn {
  user: string;
  final: string;
  status: string;
  run_id: string;
  terminal_reason: string;
  last_observation_summary: string;
  thinking_text: string;
  process: string[];
}

export interface ChatsPayload {
  workspace: string;
  chats: ChatSummary[];
}

export interface ChatPayload {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  turn_count: number;
  turns: ChatTurn[];
}

export interface ChatStartPayload {
  status: "running";
  job_id: string;
  session_id: string;
}

export interface ApprovalPayload {
  status: "ok";
  job_id: string;
  approved: boolean;
}

export interface ChatTurnResult {
  session_id: string;
  title: string;
  turn_count: number;
  run_id: string;
  status: string;
  completed: boolean;
  display_status: string;
  terminal_reason: string;
  final: string;
  last_action: string;
  last_observation_summary: string;
  error_code: string | null;
  error_message: string | null;
  process: string[];
  thinking_text: string;
}

interface EventBase {
  sequence: number;
  elapsed_ms: number;
}

interface ActionEvent extends EventBase {
  run_id: string;
  action_index: number;
  action: string;
  message: string;
  args: Record<string, unknown>;
}

export type StreamKind = "thinking" | "content" | "args";

export type ChatEvent =
  | (EventBase & { event: "chat_started"; session_id: string })
  | (EventBase & { event: "model_call_start"; run_id: string; action_index: number })
  | (EventBase & { event: "model_stream_start" })
  | (EventBase & { event: "model_stream_chunk"; kind: StreamKind; text: string; chunk_chars: number })
  | (ActionEvent & { event: "action_parsed" | "tool_start" })
  | (ActionEvent & { event: "approval_required"; reason: string })
  | (ActionEvent & { event: "approval_granted" | "approval_denied" | "approval_timed_out" })
  | (ActionEvent & { event: "observation"; status: string; summary: string })
  | (EventBase & { event: "capability_warning"; run_id: string; requested: string; fallback: string })
  | (EventBase & ChatTurnResult & { event: "final" })
  | (EventBase & { event: "error"; error: string });

export const CHAT_EVENT_NAMES = [
  "chat_started",
  "model_call_start",
  "model_stream_start",
  "model_stream_chunk",
  "action_parsed",
  "tool_start",
  "approval_required",
  "approval_granted",
  "approval_denied",
  "approval_timed_out",
  "observation",
  "capability_warning",
  "final",
  "error",
] as const;

const CHAT_EVENT_NAME_SET = new Set<string>(CHAT_EVENT_NAMES);

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isNullableString(value: unknown): value is string | null {
  return value === null || isString(value);
}

function hasActionFields(record: Record<string, unknown>) {
  return isString(record.run_id)
    && Number.isInteger(record.action_index)
    && isString(record.action)
    && isString(record.message)
    && isRecord(record.args);
}

export function parseChatEvent(value: unknown): ChatEvent | null {
  if (!isRecord(value)) return null;
  const record = value;
  if (!CHAT_EVENT_NAME_SET.has(String(record.event))) return null;
  if (!Number.isInteger(record.sequence) || typeof record.elapsed_ms !== "number") return null;
  const event = value as unknown as ChatEvent;

  switch (record.event) {
    case "chat_started":
      return isString(record.session_id) ? event : null;
    case "model_call_start":
      return isString(record.run_id) && Number.isInteger(record.action_index) ? event : null;
    case "model_stream_start":
      return event;
    case "model_stream_chunk":
      return (record.kind === "thinking" || record.kind === "content" || record.kind === "args")
        && isString(record.text)
        && Number.isInteger(record.chunk_chars)
        ? event
        : null;
    case "action_parsed":
    case "tool_start":
    case "approval_granted":
    case "approval_denied":
    case "approval_timed_out":
      return hasActionFields(record) ? event : null;
    case "approval_required":
      return hasActionFields(record) && isString(record.reason) ? event : null;
    case "observation":
      return hasActionFields(record) && isString(record.status) && isString(record.summary) ? event : null;
    case "capability_warning":
      return isString(record.run_id) && isString(record.requested) && isString(record.fallback) ? event : null;
    case "error":
      return isString(record.error) ? event : null;
    case "final":
      return isString(record.session_id)
        && isString(record.title)
        && Number.isInteger(record.turn_count)
        && isString(record.run_id)
        && isString(record.status)
        && typeof record.completed === "boolean"
        && isString(record.display_status)
        && isString(record.terminal_reason)
        && isString(record.final)
        && isString(record.last_action)
        && isString(record.last_observation_summary)
        && isNullableString(record.error_code)
        && isNullableString(record.error_message)
        && Array.isArray(record.process)
        && record.process.every(isString)
        && isString(record.thinking_text)
        ? event
        : null;
    default:
      return null;
  }
}
