import { describe, expect, it } from "vitest";
import type { ChatEvent } from "../api/types";
import { chatReducer, initialChatState } from "./state";

describe("chatReducer", () => {
  it("builds stream text and ignores replayed sequences", () => {
    const chunk: ChatEvent = {
      event: "model_stream_chunk",
      sequence: 0,
      elapsed_ms: 10,
      kind: "content",
      text: "hello",
      chunk_chars: 5,
    };
    const once = chatReducer(initialChatState, chunk);
    const twice = chatReducer(once, chunk);
    expect(twice.stream.content).toBe("hello");
    expect(twice).toBe(once);
  });

  it("holds approval until a server decision", () => {
    const required: ChatEvent = {
      event: "approval_required",
      sequence: 0,
      elapsed_ms: 12,
      run_id: "run_1",
      action_index: 1,
      action: "write_file",
      message: "Write",
      args: { path: "notes.txt" },
      reason: "Action requires approval before execution.",
    };
    const denied: ChatEvent = { ...required, event: "approval_denied", sequence: 1 };
    const waiting = chatReducer(initialChatState, required);
    const finished = chatReducer(waiting, denied);
    expect(waiting.phase).toBe("approval");
    expect(finished.phase).toBe("error");
    expect(finished.approval).toBeNull();
  });

  it.each([
    ["cancelled", "任务已停止。"],
    ["timed_out", "任务超过整轮时限，已停止。"],
    ["interrupted", "服务重启中断了本次任务。"],
    ["failed", "worker failed"],
  ] as const)("keeps %s distinct from a normal final", (terminal, message) => {
    const event = {
      event: terminal,
      sequence: 0,
      elapsed_ms: 1,
      run_id: "run_1",
      session_id: "chat_1",
      error: "worker failed",
      title: "Chat",
      turn_count: 1,
      status: "error",
      completed: false,
      display_status: "error",
      terminal_reason: terminal,
      final: "",
      last_action: "run_control",
      last_observation_summary: message,
      error_code: terminal === "cancelled" ? "CANCELLED" : "TIMEOUT",
      error_message: message,
      process: [],
      thinking_text: "",
    } as ChatEvent;

    const state = chatReducer(initialChatState, event);

    expect(state.phase).toBe("error");
    expect(state.final).toBeNull();
    expect(state.error).toBe(message);
  });
});
