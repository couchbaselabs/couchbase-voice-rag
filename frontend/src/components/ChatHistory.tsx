"use client";

import type { ChatSession } from "@/types";

interface ChatHistoryProps {
  sessions: ChatSession[];
  currentSessionId: string | null;
  onLoadSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
}

export default function ChatHistory({
  sessions,
  currentSessionId,
  onLoadSession,
  onDeleteSession,
}: ChatHistoryProps) {
  return (
    <nav aria-label="Chat history" className="space-y-1">
      <h3 className="text-sm font-semibold tracking-wider text-gray-400 uppercase">Chat History</h3>

      {sessions.length === 0 && <p className="text-xs text-gray-400">No chat history yet</p>}

      <ul className="space-y-1">
        {sessions.map((session) => {
          const isCurrent = session.session_id === currentSessionId;
          return (
            <li
              key={session.session_id}
              className={`flex items-center gap-1 rounded transition-colors ${
                isCurrent ? "border border-red-800 bg-red-900/30" : "hover:bg-gray-800"
              }`}
            >
              <button
                type="button"
                onClick={() => onLoadSession(session.session_id)}
                aria-current={isCurrent ? "page" : undefined}
                className="flex min-w-0 flex-1 cursor-pointer items-center gap-1 rounded px-2 py-1.5 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-gray-300">{session.title || "Untitled"}</p>
                  <p className="text-xs text-gray-400">
                    {new Date(session.updated_at).toLocaleDateString()}
                  </p>
                </div>
              </button>
              <button
                type="button"
                onClick={() => onDeleteSession(session.session_id)}
                aria-label={`Delete chat session ${session.title || "Untitled"}`}
                className="mr-2 shrink-0 text-gray-400 hover:text-red-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  aria-hidden="true"
                  className="h-4 w-4"
                >
                  <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
                </svg>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
