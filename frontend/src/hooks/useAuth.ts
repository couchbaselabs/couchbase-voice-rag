"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import * as api from "@/lib/api";

export function useAuth() {
  const [username, setUsername] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [mustChangePassword, setMustChangePassword] = useState(false);

  useEffect(() => {
    // The backend sets an httpOnly cookie on login; session state is derived
    // entirely from /api/auth/me so the JWT never touches JavaScript memory.
    api
      .getMe()
      .then((data) => {
        setUsername(data.username);
        setMustChangePassword(data.must_change_password);
      })
      .catch(() => {
        setUsername(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (user: string, password: string) => {
    const data = await api.login(user, password);
    setUsername(data.username);
    setMustChangePassword(data.must_change_password);
    return data;
  }, []);

  const logout = useCallback(async () => {
    await api.logout().catch(() => {});
    setUsername(null);
    setMustChangePassword(false);
  }, []);

  const clearMustChangePassword = useCallback(() => {
    setMustChangePassword(false);
  }, []);

  // Memoise the return shape so consumers that list the hook result in a
  // dependency array (useEffect, useCallback, useMemo) don't re-run on every
  // render of this hook's host component.
  return useMemo(
    () => ({
      username,
      loading,
      login,
      logout,
      mustChangePassword,
      clearMustChangePassword,
    }),
    [username, loading, login, logout, mustChangePassword, clearMustChangePassword]
  );
}
