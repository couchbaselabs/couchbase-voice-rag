"use client";

import { useState, useRef, useEffect } from "react";
import type { Message, ConnectionStatus } from "@/types";
import VoiceButton from "./VoiceButton";

interface ChatInterfaceProps {
  messages: Message[];
  status: ConnectionStatus;
  isConnected: boolean;
  isRecording: boolean;
  audioLevel: number;
  userTranscript: string;
  assistantTranscript: string;
  onStartConversation: () => void;
  onStartRecording: () => void;
  onStopRecording: () => void;
  onSendText: (text: string) => void;
}

export default function ChatInterface({
  messages,
  status,
  isConnected,
  isRecording,
  audioLevel,
  userTranscript,
  assistantTranscript,
  onStartConversation,
  onStartRecording,
  onStopRecording,
  onSendText,
}: ChatInterfaceProps) {
  const [textInput, setTextInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, userTranscript, assistantTranscript]);

  const handleSendText = (e: React.FormEvent) => {
    e.preventDefault();
    if (!textInput.trim() || !isConnected) return;
    onSendText(textInput.trim());
    setTextInput("");
  };

  return (
    <div className="flex h-full flex-col bg-[#0f0f1a]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-700 bg-[#1a1a2e] px-4 py-2">
        <h2 className="text-lg font-semibold text-gray-100">Chat</h2>
        {status === "connecting" && <span className="text-xs text-gray-400">Connecting...</span>}
      </div>

      {/* Messages */}
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 && !isConnected && status !== "connecting" && (
          <button
            type="button"
            onClick={onStartConversation}
            aria-label="Start a voice conversation with the Couchbase Voice RAG Agent"
            className="flex h-full w-full cursor-pointer flex-col items-center justify-center gap-6 bg-transparent select-none focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
          >
            <h1 className="text-2xl font-bold text-gray-100">Couchbase Voice RAG Agent</h1>
            <p className="text-gray-400">Click to start a voice conversation</p>
            <div className="flex h-24 w-24 items-center justify-center rounded-full bg-[#6aa36f] transition-all duration-200 hover:scale-105 hover:bg-[#5a8f5e]">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="white"
                aria-hidden="true"
                className="pointer-events-none ml-1 h-12 w-12"
              >
                <path d="M8 5v14l11-7z" />
              </svg>
            </div>
            <span className="text-lg text-gray-300">Start Conversation</span>
          </button>
        )}
        {status === "connecting" && messages.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-6">
            <div className="flex h-24 w-24 items-center justify-center rounded-full bg-[#6aa36f] opacity-50">
              <svg
                className="h-10 w-10 animate-spin text-white"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
            </div>
            <span className="text-lg text-gray-300">Connecting...</span>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[75%] rounded-lg px-4 py-2 ${
                msg.role === "user" ? "bg-red-600 text-white" : "bg-gray-700 text-gray-100"
              }`}
            >
              <p className="whitespace-pre-wrap">{msg.text}</p>
            </div>
          </div>
        ))}

        {/* Live user transcript */}
        {userTranscript && (
          <div className="flex justify-end">
            <div className="max-w-[75%] rounded-lg bg-red-400 px-4 py-2 text-white opacity-70">
              <p className="whitespace-pre-wrap">{userTranscript}...</p>
            </div>
          </div>
        )}

        {/* Live assistant transcript */}
        {assistantTranscript && (
          <div className="flex justify-start">
            <div className="max-w-[75%] rounded-lg bg-gray-700 px-4 py-2 text-gray-300">
              <p className="whitespace-pre-wrap">{assistantTranscript}</p>
            </div>
          </div>
        )}

        {/* Status indicator */}
        {(status === "processing" || status === "searching") && (
          <div className="flex justify-start">
            <div
              className="flex items-center gap-2 rounded-lg bg-yellow-900/50 px-4 py-2 text-sm text-yellow-400"
              role="status"
              aria-live="polite"
            >
              <svg
                className="h-4 w-4 animate-spin"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
              {status === "searching" ? "Searching knowledge base..." : "Processing..."}
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="border-t border-gray-700 bg-[#1a1a2e] p-4">
        <p className="mb-2 text-center text-xs text-gray-400">
          {isConnected
            ? "Voice input and output are available in English only."
            : "Start a conversation to enable voice and text input."}
        </p>
        <div className="relative flex items-center gap-3">
          <form onSubmit={handleSendText} className="flex flex-1 gap-2">
            <input
              type="text"
              value={textInput}
              onChange={(e) => setTextInput(e.target.value)}
              placeholder={isConnected ? "Type a message..." : "Connecting..."}
              disabled={!isConnected}
              className="flex-1 rounded-lg border border-gray-600 bg-gray-800 px-4 py-2 text-white placeholder-gray-500 focus:border-transparent focus:ring-2 focus:ring-red-500 focus:outline-none disabled:cursor-not-allowed disabled:bg-gray-900"
            />
            <button
              type="submit"
              disabled={!isConnected || !textInput.trim()}
              className="rounded-lg bg-red-600 px-4 py-2 text-white transition-colors hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Send
            </button>
          </form>
          <VoiceButton
            status={status}
            isConnected={isConnected}
            isRecording={isRecording}
            onStartRecording={onStartRecording}
            onStopRecording={onStopRecording}
          />

          {/* Recording overlay */}
          {isRecording && (
            <button
              type="button"
              onClick={onStopRecording}
              aria-label="Stop recording"
              className="absolute inset-0 z-10 flex cursor-pointer items-center justify-center gap-3 rounded-lg bg-[#1a1a2e] select-none focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
            >
              <div className="relative flex items-center justify-center">
                <span
                  aria-hidden="true"
                  className="absolute h-14 w-14 rounded-full bg-[#e8b62c]/30"
                  style={{
                    transform: `scale(${1 + audioLevel * 1.5})`,
                    opacity: 0.1 + audioLevel * 0.6,
                    transition: "transform 0.1s ease-out, opacity 0.1s ease-out",
                  }}
                />
                <span
                  aria-hidden="true"
                  className="absolute h-11 w-11 rounded-full bg-[#e8b62c]/20"
                  style={{
                    transform: `scale(${1 + audioLevel * 0.8})`,
                    opacity: 0.1 + audioLevel * 0.4,
                    transition: "transform 0.1s ease-out, opacity 0.1s ease-out",
                  }}
                />
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 24 24"
                  fill="#e8b62c"
                  aria-hidden="true"
                  className="relative h-8 w-8"
                >
                  <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm-1-9c0-.55.45-1 1-1s1 .45 1 1v6c0 .55-.45 1-1 1s-1-.45-1-1V5zm6 6c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
                </svg>
              </div>
              <span className="text-sm font-medium text-[#e8b62c]">Listening...</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
