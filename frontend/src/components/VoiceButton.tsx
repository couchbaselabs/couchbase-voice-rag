"use client";

import type { ConnectionStatus } from "@/types";

interface VoiceButtonProps {
  status: ConnectionStatus;
  isConnected: boolean;
  isRecording: boolean;
  onStartRecording: () => void;
  onStopRecording: () => void;
}

export default function VoiceButton({
  status,
  isConnected,
  isRecording,
  onStartRecording,
  onStopRecording,
}: VoiceButtonProps) {
  const handleClick = () => {
    if (isRecording) {
      onStopRecording();
    } else {
      onStartRecording();
    }
  };

  const statusText: Record<ConnectionStatus, string> = {
    idle: "Disconnected",
    connecting: "Connecting...",
    connected: "Ready",
    listening: "Listening...",
    processing: "Processing...",
    searching: "Searching knowledge base...",
    searching_web: "Searching the web...",
    responding: "Responding...",
    error: "Error",
  };

  return (
    <div className="flex flex-col items-center gap-2">
      <button
        type="button"
        onClick={handleClick}
        aria-label={isRecording ? "Stop recording" : "Start voice recording"}
        aria-pressed={isRecording}
        disabled={
          !isConnected ||
          status === "processing" ||
          status === "searching" ||
          status === "searching_web" ||
          status === "responding"
        }
        className={`flex h-16 w-16 items-center justify-center rounded-full transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 ${
          isRecording
            ? "animate-pulse bg-[#e8b62c] shadow-lg shadow-[#e8b62c]/50 hover:bg-[#d4a528]"
            : isConnected
              ? "bg-[#6aa36f] hover:bg-[#5a8f5e]"
              : "cursor-not-allowed bg-gray-600"
        } disabled:cursor-not-allowed disabled:opacity-50`}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="white"
          aria-hidden="true"
          className="h-8 w-8"
        >
          {isRecording ? (
            <rect x="6" y="6" width="12" height="12" rx="2" />
          ) : (
            <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm-1-9c0-.55.45-1 1-1s1 .45 1 1v6c0 .55-.45 1-1 1s-1-.45-1-1V5zm6 6c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
          )}
        </svg>
      </button>
      <span className="text-xs text-gray-400" role="status" aria-live="polite">
        {statusText[status]}
      </span>
    </div>
  );
}
