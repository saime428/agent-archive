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
};

export function chatReducer(state: ChatState, event: ChatEvent): ChatState {
  if (event.sequence <= state.lastSequence) return state;
  const next = { ...state, lastSequence: event.sequence };

  switch (event.event) {
    case "chat_started":
    case "model_call_start":
    case "model_stream_start":
      return { ...next, phase: "thinking" };
    case "model_stream_chunk":
      return {
        ...next,
        phase: "stream",
        stream: { ...state.stream, [event.kind]: state.stream[event.kind] + event.text },
      };
    case "action_parsed":
    case "tool_start":
    case "observation":
      return { ...next, phase: "tool", process: [...state.process, event] };
    case "approval_required":
      return { ...next, phase: "approval", approval: event, process: [...state.process, event] };
    case "approval_granted":
      return { ...next, phase: "tool", approval: null, process: [...state.process, event] };
    case "approval_denied":
    case "approval_timed_out":
      return { ...next, phase: "error", approval: null, process: [...state.process, event] };
    case "capability_warning":
      return { ...next, notices: [...state.notices, `${event.requested} unavailable; using ${event.fallback}.`] };
    case "final":
      return { ...next, phase: "final", approval: null, final: event, error: null };
    case "error":
      return { ...next, phase: "error", approval: null, error: event.error };
  }
}

export function recoveringState(state: ChatState): ChatState {
  return { ...state, phase: "recovering" };
}
