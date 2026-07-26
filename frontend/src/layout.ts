export const LAYOUT_KEY = "agent.frontend.layout";
export const WORKSPACE_VIEWS = ["files", "git", "terminal", "runs", "system"] as const;

export type WorkspaceView = (typeof WORKSPACE_VIEWS)[number];

export interface LayoutState {
  railOpen: boolean;
  railWidth: number;
  canvasEnabled: boolean;
  workspaceView: WorkspaceView;
}

export const DEFAULT_LAYOUT: LayoutState = {
  railOpen: true,
  railWidth: 326,
  canvasEnabled: true,
  workspaceView: "system",
};

interface LayoutReader {
  getItem(key: string): string | null;
}

interface LayoutWriter {
  setItem(key: string, value: string): void;
}

export function loadLayout(storage?: LayoutReader): LayoutState {
  try {
    const value = JSON.parse((storage ?? window.localStorage).getItem(LAYOUT_KEY) || "null") as Record<string, unknown> | null;
    if (!value || typeof value !== "object" || Array.isArray(value)) return { ...DEFAULT_LAYOUT };
    const railWidth = typeof value.railWidth === "number" && Number.isFinite(value.railWidth)
      ? Math.min(420, Math.max(260, value.railWidth))
      : DEFAULT_LAYOUT.railWidth;
    const workspaceView = typeof value.workspaceView === "string" && WORKSPACE_VIEWS.includes(value.workspaceView as WorkspaceView)
      ? value.workspaceView as WorkspaceView
      : DEFAULT_LAYOUT.workspaceView;
    return {
      railOpen: typeof value.railOpen === "boolean" ? value.railOpen : DEFAULT_LAYOUT.railOpen,
      railWidth,
      canvasEnabled: typeof value.canvasEnabled === "boolean" ? value.canvasEnabled : DEFAULT_LAYOUT.canvasEnabled,
      workspaceView,
    };
  } catch {
    return { ...DEFAULT_LAYOUT };
  }
}

export function saveLayout(layout: LayoutState, storage?: LayoutWriter): void {
  try {
    (storage ?? window.localStorage).setItem(LAYOUT_KEY, JSON.stringify(layout));
  } catch {
    // Browser policy or quota can disable persistence; the in-memory layout remains usable.
  }
}
