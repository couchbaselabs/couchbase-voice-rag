import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/msw-server";

import { API_BASE } from "./constants";
import { ApiError, getMe, login } from "./api";

describe("fetchJSON via ApiError", () => {
  it("returns parsed JSON on 2xx", async () => {
    server.use(
      http.get(`${API_BASE}/auth/me`, () =>
        HttpResponse.json({ username: "tester", must_change_password: false })
      )
    );
    const me = await getMe();
    expect(me.username).toBe("tester");
    expect(me.must_change_password).toBe(false);
  });

  it("throws ApiError with status, detail, and requestId on 401", async () => {
    server.use(
      http.get(`${API_BASE}/auth/me`, () =>
        HttpResponse.json(
          { detail: "Not authenticated" },
          { status: 401, headers: { "X-Request-ID": "req-abc-123" } }
        )
      )
    );
    const err = await getMe().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    const api = err as ApiError;
    expect(api.status).toBe(401);
    expect(api.detail).toBe("Not authenticated");
    expect(api.requestId).toBe("req-abc-123");
  });

  it("captures X-Request-ID even when server sends no detail", async () => {
    server.use(
      http.get(`${API_BASE}/auth/me`, () =>
        HttpResponse.json({}, { status: 500, headers: { "X-Request-ID": "req-xyz-500" } })
      )
    );
    const err = (await getMe().catch((e: unknown) => e)) as ApiError;
    expect(err.requestId).toBe("req-xyz-500");
    // Falls back to HTTP status text when server omits detail.
    expect(err.detail.length).toBeGreaterThan(0);
  });

  it("falls back to HTTP statusText when body is not JSON", async () => {
    server.use(
      http.get(`${API_BASE}/auth/me`, () =>
        HttpResponse.text("not-json", { status: 502, statusText: "Bad Gateway" })
      )
    );
    const err = (await getMe().catch((e: unknown) => e)) as ApiError;
    expect(err.status).toBe(502);
    expect(err.detail).toBe("Bad Gateway");
  });

  it("surfaces 429 rate-limit status", async () => {
    server.use(
      http.post(`${API_BASE}/auth/login`, () =>
        HttpResponse.json({ detail: "Rate limit exceeded: 10 per 1 minute" }, { status: 429 })
      )
    );
    const err = (await login("u", "p").catch((e: unknown) => e)) as ApiError;
    expect(err.status).toBe(429);
    expect(err.detail).toContain("Rate limit");
  });
});
