import { CHAT_EVENT_NAMES, parseChatEvent, type ChatEvent } from "./types";

export type StreamStatus = "connected" | "retrying" | "recovering" | "closed";

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

  const stop = () => {
    if (closed) return;
    closed = true;
    source?.close();
    options.onStatus?.("closed");
  };

  const open = () => {
    if (closed) return;
    const next = createSource(`/api/chat/events?job_id=${encodeURIComponent(options.jobId)}`);
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
        if (event.event === "final" || event.event === "error") stop();
      });
    }

    next.onerror = () => {
      if (closed) return;
      next.close();
      if (retries === 0) {
        retries += 1;
        options.onStatus?.("retrying");
        queueMicrotask(open);
        return;
      }
      closed = true;
      options.onStatus?.("recovering");
      options.onRecover(options.sessionId);
    };
  };

  open();
  return stop;
}
