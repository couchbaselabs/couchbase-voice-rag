"use client";

import Image from "next/image";
import { useState } from "react";

import { isApiError, toastApiError } from "@/lib/errors";

interface LoginFormProps {
  onLogin: (username: string, password: string) => Promise<void>;
}

export default function LoginForm({ onLogin }: LoginFormProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await onLogin(username, password);
    } catch (err: unknown) {
      if (isApiError(err) && err.status === 401) {
        // Keep the inline message for the standard "wrong credentials" case —
        // a toast would disappear before the user finishes reading.
        setError("Invalid username or password.");
      } else {
        toastApiError(err, "Login failed. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0a0a0a]">
      <div className="w-full max-w-md rounded-lg border border-gray-700 bg-[#1a1a2e] p-8 shadow-lg">
        <div className="mb-4 flex justify-center">
          <Image src="/couchbase-logo.png" alt="Couchbase" width={48} height={48} priority />
        </div>
        <h1 className="mb-6 text-center text-2xl font-bold text-gray-100">
          Couchbase Realtime Voice RAG
        </h1>
        <form
          onSubmit={(e) => {
            void handleSubmit(e);
          }}
          className="space-y-4"
        >
          <div>
            <label htmlFor="username" className="mb-1 block text-sm font-medium text-gray-300">
              Username
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-md border border-gray-600 bg-gray-800 px-3 py-2 text-white focus:border-transparent focus:ring-2 focus:ring-red-500 focus:outline-none"
              required
            />
          </div>
          <div>
            <label htmlFor="password" className="mb-1 block text-sm font-medium text-gray-300">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-gray-600 bg-gray-800 px-3 py-2 text-white focus:border-transparent focus:ring-2 focus:ring-red-500 focus:outline-none"
              required
            />
          </div>
          {error && <p className="text-sm text-red-400">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-md bg-red-600 px-4 py-2 text-white transition-colors hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "Logging in..." : "Login"}
          </button>
        </form>
      </div>
    </div>
  );
}
