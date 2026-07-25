import { CHAT_EVENT_NAMES, parseChatEvent, type ChatEvent } from "./types";

export type StreamStatus = "connected" | "retrying" | "recovering" | "closed";
const TERMINAL_EVENTS = new Set<ChatEvent["event"]>(["final", "cancelled", "timed_out", "interrupted", "failed"]);

export function isTerminalChatEvent(event: ChatEvent): boolean {
  return TERMINAL_EVENTS.has(event.event);
}

interface EventSourceLike {
  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void;
  close(): void;
  onopen: (() => void) | null;
  onerror: (() => void) | null;
}

interface SubscribeOptions {
  jobId: string;
  sessionId: string;
  onEvent: (event: ChatEvent) => void;
  onRecover: (sessionId: string) => void;
  onStatus?: (status: StreamStatus) => void;
  createSource?: (url: string) => EventSourceLike;
}

export function subscribeChatJob(options: SubscribeOptions): () => void {
  const createSource = options.createSource ?? ((url) => new EventSource(url) as unknown as EventSourceLike);
  let source: EventSourceLike | null = null;
  let closed = false;
  let retries = 0;
  let lastSequence = -1;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let recoveryNotified = false;

  const stop = () => {
    if (closed) return;
    closed = true;
    if (retryTimer !== null) clearTimeout(retryTimer);
    source?.close();
    options.onStatus?.("closed");
  };

  const open = () => {
    if (closed) return;
    const next = createSource(
      `/api/chat/events?job_id=${encodeURIComponent(options.jobId)}&after=${lastSequence + 1}`,
    );
    source = next;
    next.onopen = () => options.onStatus?.("connected");

    for (const eventName of CHAT_EVENT_NAMES) {
      next.addEventListener(eventName, (message) => {
        if (closed) return;
        let raw: unknown;
        try {
          raw = JSON.parse(message.data);
        } catch {
          next.onerror?.();
          return;
        }
        const event = parseChatEvent(raw);
        if (!event || event.sequence <= lastSequence) return;
        lastSequence = event.sequence;
        options.onEvent(event);
        if (isTerminalChatEvent(event)) stop();
      });
    }

    next.onerror = () => {
      if (closed || source !== next || retryTimer !== null) return;
      next.close();
      retries += 1;
      if (retries === 1) {
        options.onStatus?.("retrying");
        queueMicrotask(open);
        return;
      }
      options.onStatus?.("recovering");
      if (!recoveryNotified) {
        recoveryNotified = true;
        options.onRecover(options.sessionId);
      }
      const delay = Math.min(1_000, 100 * (2 ** Math.min(retries, 3)));
      retryTimer = setTimeout(() => {
        retryTimer = null;
        open();
      }, delay);
    };
  };

  open();
  return stop;
}
