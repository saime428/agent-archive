import { describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient } from "./client";

describe("createApiClient", () => {
  it("sends one JSON request and returns the payload", async () => {
    const fetcher = vi.fn(async () => new Response('{"status":"running","job_id":"job_1","session_id":"chat_1"}'));
    const client = createApiClient(fetcher as typeof fetch);

    await expect(client.startChat("hello", "chat_1")).resolves.toMatchObject({ job_id: "job_1" });
    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledWith(
      "/api/chat/start",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ message: "hello", session_id: "chat_1" }),
      }),
    );
  });

  it("sends lifecycle timeout, cancel, and safe resume payloads", async () => {
    const fetcher = vi.fn(async (...request: Parameters<typeof fetch>) => {
      void request;
      return new Response('{"status":"running","job_id":"job_2","session_id":"chat_1","run_id":"run_2"}');
    });
    const client = createApiClient(fetcher as typeof fetch);

    await client.startChat("first", "chat_1", 120);
    await client.cancelChat("job_1");
    await client.resumeChat("job_1", "continue safely", 300);

    expect(fetcher.mock.calls.map(([path, init]) => [path, init?.body])).toEqual([
      ["/api/chat/start", JSON.stringify({ message: "first", session_id: "chat_1", timeout_seconds: 120 })],
      ["/api/chat/cancel", JSON.stringify({ job_id: "job_1" })],
      ["/api/chat/resume", JSON.stringify({ job_id: "job_1", message: "continue safely", timeout_seconds: 300 })],
    ]);
  });

  it("converts backend errors without retrying", async () => {
    const fetcher = vi.fn(async () => new Response('{"error":"already active"}', { status: 400 }));
    const client = createApiClient(fetcher as typeof fetch);

    await expect(client.startChat("hello")).rejects.toEqual(new ApiError("already active", 400, { error: "already active" }));
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("encodes spaces as %20 (not +) so the backend unquote() resolves paths", async () => {
    const fetcher = vi.fn(async () => new Response('{"path":"a b.txt","content":"x","truncated":false,"size":1}'));
    const client = createApiClient(fetcher as typeof fetch);

    await client.getFile("dir name/a b.txt");

    // %20 (not +) — the backend uses unquote(), which does not turn + into a space.
    expect(fetcher).toHaveBeenCalledWith("/api/file?path=dir%20name%2Fa%20b.txt", expect.anything());
  });

  it("encodes Unicode file paths", async () => {
    const fetcher = vi.fn(async () => new Response('{"path":"报告.md","content":"x","truncated":false,"size":1}'));
    const client = createApiClient(fetcher as typeof fetch);

    await client.getFile("报告.md");

    expect(fetcher).toHaveBeenCalledWith(`/api/file?path=${encodeURIComponent("报告.md")}`, expect.anything());
  });

  it("omits the query string when listFiles has no path", async () => {
    const fetcher = vi.fn(async () => new Response('{"path":".","entries":[]}'));
    const client = createApiClient(fetcher as typeof fetch);

    await client.listFiles();

    expect(fetcher).toHaveBeenCalledWith("/api/files", expect.anything());
  });

  it("sends diff with path and snapshot query params", async () => {
    const fetcher = vi.fn(
      async () => new Response('{"path":"a.txt","snapshot_path":"s","diff":"","truncated":false,"current_exists":true,"snapshot_missing":false}'),
    );
    const client = createApiClient(fetcher as typeof fetch);

    await client.getDiff("a.txt", "snap_1");

    expect(fetcher).toHaveBeenCalledWith("/api/diff?path=a.txt&snapshot=snap_1", expect.anything());
  });

  it("restores using the snapshot_path request body key", async () => {
    const fetcher = vi.fn(async () => new Response('{"status":"ok","action":"restored","path":"a.txt","snapshot_path":"s"}'));
    const client = createApiClient(fetcher as typeof fetch);

    await client.restoreSnapshot("a.txt", "snap_dir/snap_1");

    expect(fetcher).toHaveBeenCalledWith(
      "/api/snapshot/restore",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ path: "a.txt", snapshot_path: "snap_dir/snap_1" }),
      }),
    );
  });

  it("posts only whitelisted config keys as given", async () => {
    const fetcher = vi.fn(async () => new Response('{"workspace":"w","config":{},"diagnostics":{},"status":"ok"}'));
    const client = createApiClient(fetcher as typeof fetch);

    await client.saveConfig({ mode: "auto", default_skills: ["code-dev"] });

    expect(fetcher).toHaveBeenCalledWith(
      "/api/config",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ mode: "auto", default_skills: ["code-dev"] }),
      }),
    );
  });

  it("encodes run id in the path segment", async () => {
    const fetcher = vi.fn(async () => new Response('{"run_id":"run 1"}'));
    const client = createApiClient(fetcher as typeof fetch);

    await client.getRun("run 1");

    expect(fetcher).toHaveBeenCalledWith("/api/runs/run%201", expect.anything());
  });
});
