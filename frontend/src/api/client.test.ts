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

  it("converts backend errors without retrying", async () => {
    const fetcher = vi.fn(async () => new Response('{"error":"already active"}', { status: 400 }));
    const client = createApiClient(fetcher as typeof fetch);

    await expect(client.startChat("hello")).rejects.toEqual(new ApiError("already active", 400, { error: "already active" }));
    expect(fetcher).toHaveBeenCalledOnce();
  });
});
