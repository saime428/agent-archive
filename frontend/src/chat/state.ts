import type { ChatEvent, ChatTurnResult, StreamKind } from "../api/types";

export type ChatPhase = "idle" | "thinking" | "stream" | "tool" | "approval" | "final" | "error" | "recovering";

export interface ChatState {
  phase: ChatPhase;
  lastSequence: number;
  stream: Record<StreamKind, string>;
  process: ChatEvent[];
  approval: Extract<ChatEvent, { event: "approval_required" }> | null;
  final: ChatTurnResult | null;
  error: string | null;
  notices: string[];
  /** Action name of the most recent tool/approval event, for the phase indicator. */
  lastAction: string | null;
  /** Kind of the most recent model stream chunk, for the phase indicator. */
  streamKind: StreamKind | null;
  /** Latest phase-driving SSE event; warnings do not replace it. */
  phaseEvent: ChatEvent | null;
}

export const initialChatState: ChatState = {
  phase: "idle",
  lastSequence: -1,
  stream: { thinking: "", content: "", args: "" },
  process: [],
  approval: null,
  final: null,
  error: null,
  notices: [],
  lastAction: null,
  streamKind: null,
  phaseEvent: null,
};

export function chatReducer(state: ChatState, event: ChatEvent): ChatState {
  if (event.sequence <= state.lastSequence) return state;
  const next = { ...state, lastSequence: event.sequence, phaseEvent: event.event === "capability_warning" ? state.phaseEvent : event };

  switch (event.event) {
    case "chat_started":
    case "model_call_start":
    case "model_stream_start":
      return { ...next, phase: "thinking", streamKind: null };
    case "model_stream_chunk":
      return {
        ...next,
        phase: "stream",
        streamKind: event.kind,
        stream: { ...state.stream, [event.kind]: state.stream[event.kind] + event.text },
      };
    case "action_parsed":
    case "tool_start":
    case "observation":
      return { ...next, phase: "tool", lastAction: event.action, process: [...state.process, event] };
    case "approval_required":
      return { ...next, phase: "approval", approval: event, lastAction: event.action, process: [...state.process, event] };
    case "approval_granted":
      return { ...next, phase: "tool", approval: null, lastAction: event.action, process: [...state.process, event] };
    case "approval_denied":
    case "approval_timed_out":
      return { ...next, phase: "error", approval: null, lastAction: event.action, process: [...state.process, event] };
    case "capability_warning":
      return { ...next, notices: [...state.notices, `${event.requested} unavailable; using ${event.fallback}.`] };
    case "final":
      return { ...next, phase: "final", approval: null, final: event, error: null };
    case "cancelled":
      return { ...next, phase: "error", approval: null, final: null, error: "任务已停止。" };
    case "timed_out":
      return { ...next, phase: "error", approval: null, final: null, error: "任务超过整轮时限，已停止。" };
    case "interrupted":
      return { ...next, phase: "error", approval: null, final: null, error: "服务重启中断了本次任务。" };
    case "failed":
      return { ...next, phase: "error", approval: null, final: null, error: event.error };
    case "error":
      return { ...next, phase: "error", approval: null, error: event.error };
  }
}

export function recoveringState(state: ChatState): ChatState {
  return { ...state, phase: "recovering", phaseEvent: null };
}
