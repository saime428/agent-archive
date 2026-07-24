import type {
  ApprovalPayload,
  ChatPayload,
  ChatStartPayload,
  ChatsPayload,
  HealthPayload,
} from "./types";

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
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
export const api = createApiClient();
