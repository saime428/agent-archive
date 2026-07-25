import { describe, expect, it, vi } from "vitest";
import { subscribeChatJob } from "./sse";

class FakeSource {
  listeners = new Map<string, (event: MessageEvent<string>) => void>();
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
    this.listeners.set(type, listener);
  }

  emit(type: string, payload: object) {
    this.listeners.get(type)?.({ data: JSON.stringify(payload) } as MessageEvent<string>);
  }
}

describe("subscribeChatJob", () => {
  it("deduplicates replayed sequences and closes on final", async () => {
    const sources: FakeSource[] = [];
    const urls: string[] = [];
    const events: string[] = [];
    const stop = subscribeChatJob({
      jobId: "job 1",
      sessionId: "chat_1",
      onEvent: (event) => events.push(event.event),
      onRecover: vi.fn(),
      createSource: (url) => {
        urls.push(url);
        const source = new FakeSource();
        sources.push(source);
        return source;
      },
    });
    sources[0].emit("chat_started", { event: "chat_started", sequence: 0, elapsed_ms: 0, session_id: "chat_1" });
    sources[0].onerror?.();
    await Promise.resolve();
    expect(urls).toEqual([
      "/api/chat/events?job_id=job%201&after=0",
      "/api/chat/events?job_id=job%201&after=1",
    ]);
    sources[1].emit("chat_started", { event: "chat_started", sequence: 0, elapsed_ms: 0, session_id: "chat_1" });
    sources[1].emit("final", {
      event: "final",
      sequence: 1,
      elapsed_ms: 4,
      session_id: "chat_1",
      title: "Chat",
      turn_count: 1,
      run_id: "run_1",
      status: "ok",
      completed: true,
      display_status: "completed",
      terminal_reason: "done",
      final: "Done",
      last_action: "done",
      last_observation_summary: "Done.",
      error_code: null,
      error_message: null,
      process: [],
      thinking_text: "",
    });

    expect(events).toEqual(["chat_started", "final"]);
    expect(sources[1].close).toHaveBeenCalledOnce();
    stop();
  });

  it.each([
    ["cancelled", { session_id: "chat_1", title: "Chat", turn_count: 1, run_id: "run_1", status: "error", completed: false, display_status: "error", terminal_reason: "cancelled", final: "", last_action: "run_control", last_observation_summary: "Run cancelled.", error_code: "CANCELLED", error_message: "Run cancelled.", process: [], thinking_text: "" }],
    ["timed_out", { session_id: "chat_1", title: "Chat", turn_count: 1, run_id: "run_1", status: "error", completed: false, display_status: "error", terminal_reason: "timed_out", final: "", last_action: "run_control", last_observation_summary: "Run timed out.", error_code: "TIMEOUT", error_message: "Run timed out.", process: [], thinking_text: "" }],
    ["interrupted", { session_id: "chat_1", run_id: "run_1" }],
    ["failed", { run_id: "run_1", error: "worker failed" }],
  ])("closes on %s terminal events", (event, fields) => {
    const source = new FakeSource();
    const stop = subscribeChatJob({
      jobId: "job_1",
      sessionId: "chat_1",
      onEvent: vi.fn(),
      onRecover: vi.fn(),
      createSource: () => source,
    });

    source.emit(event, { event, sequence: 0, elapsed_ms: 1, ...fields });

    expect(source.close).toHaveBeenCalledOnce();
    stop();
  });

  it("keeps the stream open for the backward-compatible nonterminal error event", () => {
    const source = new FakeSource();
    const onEvent = vi.fn();
    subscribeChatJob({
      jobId: "job_1",
      sessionId: "chat_1",
      onEvent,
      onRecover: vi.fn(),
      createSource: () => source,
    });

    source.emit("error", { event: "error", sequence: 0, elapsed_ms: 1, error: "worker failed" });

    expect(onEvent).toHaveBeenCalledOnce();
    expect(source.close).not.toHaveBeenCalled();
  });

  it("keeps reconnecting after history recovery until a durable terminal arrives", async () => {
    vi.useFakeTimers();
    const sources: FakeSource[] = [];
    const recover = vi.fn();
    try {
      subscribeChatJob({
        jobId: "job_1",
        sessionId: "chat_1",
        onEvent: vi.fn(),
        onRecover: recover,
        createSource: () => {
          const source = new FakeSource();
          sources.push(source);
          return source;
        },
      });
      sources[0].onerror?.();
      await vi.runOnlyPendingTimersAsync();
      sources[1].onerror?.();
      expect(recover).toHaveBeenCalledWith("chat_1");
      await vi.runOnlyPendingTimersAsync();
      sources[2].emit("interrupted", {
        event: "interrupted",
        sequence: 0,
        elapsed_ms: 2,
        run_id: "run_1",
        session_id: "chat_1",
      });
      expect(sources[2].close).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });

  it("rejects malformed known events at the adapter boundary", () => {
    const source = new FakeSource();
    const onEvent = vi.fn();
    subscribeChatJob({
      jobId: "job_1",
      sessionId: "chat_1",
      onEvent,
      onRecover: vi.fn(),
      createSource: () => source,
    });
    source.emit("model_stream_chunk", {
      event: "model_stream_chunk",
      sequence: 0,
      elapsed_ms: 1,
      kind: "invalid",
      text: "unsafe",
      chunk_chars: 6,
    });
    expect(onEvent).not.toHaveBeenCalled();
  });
});
