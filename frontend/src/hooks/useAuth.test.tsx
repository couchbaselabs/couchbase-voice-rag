import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { API_BASE } from "@/lib/constants";
import { server } from "@/test/msw-server";

import { useAuth } from "./useAuth";

describe("useAuth", () => {
  it("hydrates username from /api/auth/me on mount", async () => {
    server.use(
      http.get(`${API_BASE}/auth/me`, () =>
        HttpResponse.json({ username: "tester", must_change_password: false })
      )
    );
    const { result } = renderHook(() => useAuth());

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.username).toBe("tester");
    expect(result.current.mustChangePassword).toBe(false);
  });

  it("stays logged-out when /api/auth/me returns 401", async () => {
    server.use(
      http.get(`${API_BASE}/auth/me`, () =>
        HttpResponse.json({ detail: "Not authenticated" }, { status: 401 })
      )
    );
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.username).toBeNull();
  });

  it("login() sets username + must_change_password", async () => {
    server.use(
      http.get(`${API_BASE}/auth/me`, () =>
        HttpResponse.json({ detail: "Not authenticated" }, { status: 401 })
      ),
      http.post(`${API_BASE}/auth/login`, () =>
        HttpResponse.json({
          token: "jwt-redacted",
          username: "tester",
          must_change_password: true,
        })
      )
    );
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.login("tester", "secret");
    });

    expect(result.current.username).toBe("tester");
    expect(result.current.mustChangePassword).toBe(true);
  });

  it("logout() clears username even if the request fails", async () => {
    server.use(
      http.get(`${API_BASE}/auth/me`, () =>
        HttpResponse.json({ username: "tester", must_change_password: false })
      ),
      http.post(`${API_BASE}/auth/logout`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 })
      )
    );
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.username).toBe("tester"));

    await act(async () => {
      await result.current.logout();
    });
    expect(result.current.username).toBeNull();
  });

  it("never stores the token in localStorage (Phase F3 posture)", async () => {
    server.use(
      http.get(`${API_BASE}/auth/me`, () =>
        HttpResponse.json({ detail: "Not authenticated" }, { status: 401 })
      ),
      http.post(`${API_BASE}/auth/login`, () =>
        HttpResponse.json({
          token: "jwt-redacted",
          username: "tester",
          must_change_password: false,
        })
      )
    );
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.login("tester", "secret");
    });
    expect(localStorage.getItem("token")).toBeNull();
  });
});
