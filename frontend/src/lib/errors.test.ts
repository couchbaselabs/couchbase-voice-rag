import { beforeEach, describe, expect, it, vi } from "vitest";

import { toastMock } from "@/test/helpers";

import { ApiError } from "./api";

vi.mock("sonner", () => ({ toast: toastMock }));

describe("toastApiError", () => {
  beforeEach(() => {
    toastMock.error.mockReset();
  });

  it("returns null and uses fallback for non-ApiError", async () => {
    const { toastApiError } = await import("./errors");
    const status = toastApiError(new Error("oops"), "custom fallback");
    expect(status).toBeNull();
    expect(toastMock.error).toHaveBeenCalledWith("custom fallback");
  });

  it("maps 401 to session-expired copy", async () => {
    const { toastApiError } = await import("./errors");
    toastApiError(new ApiError(401, "Not authenticated", undefined));
    expect(toastMock.error).toHaveBeenCalledWith(expect.stringContaining("session has expired"));
  });

  it("shows the backend detail verbatim for 413", async () => {
    const { toastApiError } = await import("./errors");
    toastApiError(new ApiError(413, "File too large. Maximum size is 50MB.", undefined));
    expect(toastMock.error).toHaveBeenCalledWith(expect.stringContaining("Maximum size is 50MB"));
  });

  it("maps 429 to rate-limit copy", async () => {
    const { toastApiError } = await import("./errors");
    toastApiError(new ApiError(429, "Rate limit exceeded", undefined));
    expect(toastMock.error).toHaveBeenCalledWith(expect.stringContaining("Too many requests"));
  });

  it("includes request id in 5xx toast", async () => {
    const { toastApiError } = await import("./errors");
    toastApiError(new ApiError(500, "boom", "req-abc"));
    expect(toastMock.error).toHaveBeenCalledWith(expect.stringContaining("req-abc"));
  });

  it("returns the numeric status for ApiError", async () => {
    const { toastApiError } = await import("./errors");
    const status = toastApiError(new ApiError(400, "bad", undefined));
    expect(status).toBe(400);
  });
});
