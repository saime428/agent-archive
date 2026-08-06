import { describe, expect, it } from "vitest";
import { resolveChatOrbState } from "./Orb";

describe("resolveChatOrbState", () => {
  it("maps every animated phase onto its own orb state", () => {
    expect(resolveChatOrbState("thinking", null, null)).toBe("solving");
    expect(resolveChatOrbState("stream", null, "thinking")).toBe("weaving");
    expect(resolveChatOrbState("stream", null, "content")).toBe("composing");
    expect(resolveChatOrbState("tool", "search_files", null)).toBe("searching");
    expect(resolveChatOrbState("tool", "apply_patch", null)).toBe("shaping");
    expect(resolveChatOrbState("tool", "run_command", null)).toBe("working");
    expect(resolveChatOrbState("approval", "write_file", null)).toBe("listening");
    expect(resolveChatOrbState("recovering", null, null)).toBe("breathing");
  });

  it("shows no orb once a turn has settled", () => {
    expect(resolveChatOrbState("idle", null, null)).toBeNull();
    expect(resolveChatOrbState("final", "done", null)).toBeNull();
    expect(resolveChatOrbState("error", "run_command", null)).toBeNull();
  });

  it("falls back to working for unknown and MCP actions", () => {
    expect(resolveChatOrbState("tool", "mcp__server__do_thing", null)).toBe("working");
    expect(resolveChatOrbState("tool", null, null)).toBe("working");
  });

  it("keeps args and content on one state so native tool streams do not flicker", () => {
    // Every state change rebuilds the orb's animation loop, and native tool calls
    // interleave args with content chunk by chunk.
    expect(resolveChatOrbState("stream", null, "args")).toBe(resolveChatOrbState("stream", null, "content"));
  });

  it("reads every reading action as searching and every writing action as shaping", () => {
    for (const action of ["search_files", "web_search", "list_dir", "read_file", "read_pdf", "read_docx", "read_xlsx", "read_pptx"]) {
      expect(resolveChatOrbState("tool", action, null)).toBe("searching");
    }
    for (const action of ["write_file", "apply_patch", "write_markdown_report"]) {
      expect(resolveChatOrbState("tool", action, null)).toBe("shaping");
    }
  });
});
