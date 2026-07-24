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
});
