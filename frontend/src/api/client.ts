import type {
  ApprovalPayload,
  ChatPayload,
  ChatStartPayload,
  ChatsPayload,
  ConfigPayload,
  ConfigUpdates,
  DiffPayload,
  FilePayload,
  FilesPayload,
  HealthPayload,
  RestorePayload,
  RunDetailPayload,
  RunsPayload,
  SaveFilePayload,
  ToolsPayload,
} from "./types";

// 后端 _query_value 用 unquote()（不把 "+" 还原为空格），因此查询值必须用
// encodeURIComponent（空格 → %20），不能用 URLSearchParams（空格 → "+"）。
function queryString(params: Record<string, string | undefined>): string {
  const parts = Object.entries(params)
    .filter((entry): entry is [string, string] => typeof entry[1] === "string" && entry[1].length > 0)
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly payload: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function createApiClient(fetcher: typeof fetch = globalThis.fetch.bind(globalThis)) {
  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetcher(path, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
    const text = await response.text();
    let payload: unknown = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = text;
      }
    }
    if (!response.ok) {
      const message =
        payload && typeof payload === "object" && "error" in payload && typeof payload.error === "string"
          ? payload.error
          : `Request failed with status ${response.status}.`;
      throw new ApiError(message, response.status, payload);
    }
    return payload as T;
  }

  const post = <T>(path: string, body: Record<string, unknown>) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) });

  return {
    getHealth: () => request<HealthPayload>("/api/health"),
    listChats: () => request<ChatsPayload>("/api/chats"),
    getChat: (sessionId: string) => request<ChatPayload>(`/api/chats/${encodeURIComponent(sessionId)}`),
    startChat: (message: string, sessionId?: string) =>
      post<ChatStartPayload>("/api/chat/start", { message, ...(sessionId ? { session_id: sessionId } : {}) }),
    decideApproval: (jobId: string, approve: boolean) =>
      post<ApprovalPayload>("/api/chat/approval", { job_id: jobId, approve }),
    renameChat: (sessionId: string, title: string) =>
      post<{ status: "ok"; session_id: string; title: string }>("/api/chat/rename", {
        session_id: sessionId,
        title,
      }),
    deleteChat: (sessionId: string) =>
      post<{ status: "ok"; session_id: string; deleted: true }>("/api/chat/delete", { session_id: sessionId }),
    listFiles: (path?: string) => request<FilesPayload>(`/api/files${queryString({ path })}`),
    getFile: (path: string) => request<FilePayload>(`/api/file${queryString({ path })}`),
    saveFile: (path: string, content: string) =>
      post<SaveFilePayload>("/api/file/save", { path, content }),
    getDiff: (path: string, snapshot: string) =>
      request<DiffPayload>(`/api/diff${queryString({ path, snapshot })}`),
    restoreSnapshot: (path: string, snapshotPath: string) =>
      post<RestorePayload>("/api/snapshot/restore", { path, snapshot_path: snapshotPath }),
    listRuns: () => request<RunsPayload>("/api/runs"),
    getRun: (runId: string) => request<RunDetailPayload>(`/api/runs/${encodeURIComponent(runId)}`),
    getConfig: () => request<ConfigPayload>("/api/config"),
    saveConfig: (updates: Partial<ConfigUpdates>) => post<ConfigPayload>("/api/config", updates),
    listTools: () => request<ToolsPayload>("/api/tools"),
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
export const api = createApiClient();
