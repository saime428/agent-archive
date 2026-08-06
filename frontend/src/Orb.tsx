import { ThinkingOrb, type OrbState } from "thinking-orbs";

import type { StreamKind } from "./api/types";
import type { ChatPhase } from "./chat/state";
import { useTheme } from "./theme";

// Action names mirror ARGS_MODELS in src/agent/core/actions.py. Anything absent
// from both sets — including every dynamic MCP tool — falls through to `working`,
// so a new backend action can never break the indicator.
const READING_ACTIONS = new Set([
  "search_files",
  "web_search",
  "list_dir",
  "read_file",
  "read_pdf",
  "read_docx",
  "read_xlsx",
  "read_pptx",
]);

const WRITING_ACTIONS = new Set(["write_file", "apply_patch", "write_markdown_report"]);

/**
 * Maps a chat phase onto an orb state, or null when the phase should show no orb.
 *
 * `idle`, `final` and `error` are settled states with their own UI; animating
 * there would claim the agent is still running.
 */
export function resolveChatOrbState(
  phase: ChatPhase,
  action: string | null,
  streamKind: StreamKind | null,
): OrbState | null {
  switch (phase) {
    case "thinking":
      return "solving";
    case "stream":
      // `content` and `args` deliberately share one state: native tool calls
      // interleave both kinds, and every state change tears down and rebuilds the
      // orb's animation loop. Collapsing them keeps one switch per turn.
      return streamKind === "thinking" ? "weaving" : "composing";
    case "tool":
      if (action !== null && READING_ACTIONS.has(action)) return "searching";
      if (action !== null && WRITING_ACTIONS.has(action)) return "shaping";
      return "working";
    case "approval":
      return "listening";
    case "recovering":
      return "breathing";
    case "idle":
    case "final":
    case "error":
      return null;
  }
}

/**
 * Decorative pending indicator. The surrounding copy carries the meaning, so the
 * canvas stays aria-hidden and no live region is added.
 */
export function Orb({ state }: { state: OrbState | null }) {
  const { resolvedMode } = useTheme();
  if (state === null) return null;
  return <ThinkingOrb state={state} size={20} theme={resolvedMode} aria-hidden="true" />;
}
