"use client";

import Image from "next/image";
import { useCallback, useEffect, useRef, useState } from "react";

import * as api from "@/lib/api";
import type { ChatSession, UploadedFile } from "@/types";

import ChatHistory from "./ChatHistory";
import FileUpload from "./FileUpload";

interface SidebarProps {
  username: string;
  currentSessionId: string | null;
  sessionRefreshKey: number;
  onNewChat: () => void;
  onLoadSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
  onLogout: () => void;
  onDocumentsChange: () => void;
  onOpenSettings?: () => void;
  onOpenChangePassword?: () => void;
}

export default function Sidebar({
  username,
  currentSessionId,
  sessionRefreshKey,
  onNewChat,
  onLoadSession,
  onDeleteSession,
  onLogout,
  onDocumentsChange,
  onOpenSettings,
  onOpenChangePassword,
}: SidebarProps) {
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement | null>(null);

  const refreshFiles = useCallback(async () => {
    try {
      const data = await api.listDocuments();
      setFiles(data);
    } catch (err) {
      console.error("Failed to load documents:", err);
    }
  }, []);

  const refreshSessions = useCallback(async () => {
    try {
      const data = await api.listSessions();
      setSessions(data);
    } catch (err) {
      console.error("Failed to load sessions:", err);
    }
  }, []);

  useEffect(() => {
    // Phase F5 should migrate these to a query library (SWR / TanStack Query)
    // which subscribes externally; until then the setState cascade is expected.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshFiles();
    void refreshSessions();
  }, [refreshFiles, refreshSessions, sessionRefreshKey]);

  useEffect(() => {
    if (!menuOpen) return;
    const handler = (e: MouseEvent) => {
      if (!userMenuRef.current) return;
      if (!userMenuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [menuOpen]);

  const handleDocumentsRefresh = () => {
    void refreshFiles();
    onDocumentsChange();
  };

  const closeMenuThen = (cb: () => void) => () => {
    setMenuOpen(false);
    cb();
  };

  return (
    <aside className="flex h-screen w-72 flex-col border-r border-gray-700 bg-[#1a1a2e]">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-gray-700 p-4">
        <Image src="/couchbase-logo.png" alt="Couchbase" width={32} height={32} />
        <h1 className="text-lg font-bold text-red-400">Couchbase Voice RAG</h1>
      </div>

      {/* Actions */}
      <div className="flex gap-2 px-4 py-3">
        <button
          onClick={onNewChat}
          className="flex-1 rounded-md bg-red-600 px-3 py-1.5 text-sm text-white transition-colors hover:bg-red-700"
        >
          New Chat
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 space-y-6 overflow-y-auto px-4 pb-4">
        <FileUpload files={files} onRefresh={handleDocumentsRefresh} />
        <hr className="border-gray-700" />
        <ChatHistory
          sessions={sessions}
          currentSessionId={currentSessionId}
          onLoadSession={onLoadSession}
          onDeleteSession={onDeleteSession}
        />
      </div>

      {/* Footer: user identity with upward popover */}
      <div ref={userMenuRef} className="relative border-t border-gray-700">
        {menuOpen && (
          <div
            role="menu"
            className="absolute right-4 bottom-full left-4 mb-2 overflow-hidden rounded-md border border-gray-600 bg-gray-800 text-sm shadow-lg"
          >
            {onOpenChangePassword && (
              <button
                type="button"
                role="menuitem"
                onClick={closeMenuThen(onOpenChangePassword)}
                className="block w-full px-3 py-2 text-left text-gray-200 transition-colors hover:bg-gray-700"
              >
                Change Password
              </button>
            )}
            {onOpenSettings && (
              <button
                type="button"
                role="menuitem"
                onClick={closeMenuThen(onOpenSettings)}
                className="block w-full px-3 py-2 text-left text-gray-200 transition-colors hover:bg-gray-700"
              >
                Settings
              </button>
            )}
            <button
              type="button"
              role="menuitem"
              onClick={closeMenuThen(onLogout)}
              className="block w-full border-t border-gray-700 px-3 py-2 text-left text-gray-200 transition-colors hover:bg-gray-700"
            >
              Logout
            </button>
          </div>
        )}
        <button
          type="button"
          onClick={() => setMenuOpen((v) => !v)}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm text-gray-300 transition-colors hover:bg-gray-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-inset"
        >
          <span className="h-2 w-2 flex-shrink-0 rounded-full bg-green-500" aria-hidden="true" />
          <span className="truncate">Logged in as {username}</span>
        </button>
        {process.env.NEXT_PUBLIC_BUILD_TIME && (
          <p className="border-t border-gray-700 px-4 py-2 text-center text-[10px] text-gray-600">
            Deployed: {process.env.NEXT_PUBLIC_BUILD_TIME}
          </p>
        )}
      </div>
    </aside>
  );
}
