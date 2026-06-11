"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import * as api from "@/lib/api";

export default function ChangePasswordPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-[#0a0a0a]">
          <div className="text-gray-400">Loading...</div>
        </div>
      }
    >
      <ChangePasswordInner />
    </Suspense>
  );
}

function ChangePasswordInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { username, loading, logout, mustChangePassword, clearMustChangePassword } = useAuth();

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [status, setStatus] = useState<"idle" | "loading">("idle");
  const [error, setError] = useState("");

  const forced = searchParams.get("forced") === "1" || mustChangePassword;

  useEffect(() => {
    if (!loading && !username) {
      router.replace("/login");
    }
  }, [loading, username, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (newPassword.length < 4) {
      setError("New password must be at least 4 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("New password and confirmation do not match.");
      return;
    }

    setStatus("loading");
    try {
      await api.changePassword(currentPassword, newPassword);
      clearMustChangePassword();
      await logout();
      alert("Password changed. Please log in again.");
      router.replace("/login");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to change password";
      setError(message);
      setStatus("idle");
    }
  };

  if (loading || !username) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0a0a0a]">
        <div className="text-gray-400">Loading...</div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0a0a0a] p-4">
      <div className="w-full max-w-md rounded-lg border border-gray-700 bg-[#1a1a2e] p-8 shadow-lg">
        <h1 className="mb-2 text-xl font-bold text-gray-100">
          {forced ? "Set a New Password" : "Change Password"}
        </h1>
        <p className="mb-6 text-sm text-gray-400">
          {forced
            ? "For security, you must change the default password before continuing."
            : "Changing the password will log out all existing sessions."}
        </p>

        <form
          onSubmit={(e) => {
            void handleSubmit(e);
          }}
          className="space-y-4"
        >
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-300">Current Password</label>
            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
              autoFocus
              className="w-full rounded-md border border-gray-600 bg-gray-800 px-3 py-2 text-white focus:ring-2 focus:ring-red-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-300">New Password</label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={4}
              className="w-full rounded-md border border-gray-600 bg-gray-800 px-3 py-2 text-white focus:ring-2 focus:ring-red-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-300">
              Confirm New Password
            </label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={4}
              className="w-full rounded-md border border-gray-600 bg-gray-800 px-3 py-2 text-white focus:ring-2 focus:ring-red-500 focus:outline-none"
            />
          </div>

          {error && (
            <div className="rounded-md border border-red-800 bg-red-900/30 px-4 py-3">
              <p className="text-sm text-red-400">{error}</p>
            </div>
          )}

          <button
            type="submit"
            disabled={status === "loading"}
            className="w-full rounded-md bg-red-600 px-4 py-2 text-white transition-colors hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {status === "loading" ? "Changing..." : "Change Password"}
          </button>

          {!forced && (
            <button
              type="button"
              onClick={() => router.back()}
              className="w-full rounded-md bg-gray-700 px-4 py-2 text-gray-300 transition-colors hover:bg-gray-600"
            >
              Cancel
            </button>
          )}
        </form>
      </div>
    </div>
  );
}
