import { state } from "./state.js";
import { postJson } from "./api.js";

const CHAT_EVENT_NAMES = [
  "chat_started",
  "model_call_start",
  "model_stream_start",
  "action_parsed",
  "tool_start",
  "approval_required",
  "approval_granted",
  "approval_denied",
  "observation",
  "final",
  "error",
];

export function openChatEventSource(jobId, handlers = {}) {
  closeChatEventSource();
  const source = new EventSource(`/api/chat/events?job_id=${encodeURIComponent(jobId)}`);
  state.eventSource = source;
  for (const eventName of CHAT_EVENT_NAMES) {
    source.addEventListener(eventName, (event) => handleChatEvent(event, handlers));
  }
  source.onerror = () => handlers.onError?.();
}

function handleChatEvent(event, handlers = {}) {
  const payload = JSON.parse(event.data);
  handlers.onEvent?.(payload);
}

export function closeChatEventSource() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
}

export async function submitApproval(jobId, approve, button) {
  if (button) {
    button.disabled = true;
  }
  await postJson("/api/chat/approval", { job_id: jobId, approve });
}
