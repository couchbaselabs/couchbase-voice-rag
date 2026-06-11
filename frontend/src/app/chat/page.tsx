"use client";

import { useEffect, useCallback, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { useRealtimeAudio } from "@/hooks/useRealtimeAudio";
import ChatInterface from "@/components/ChatInterface";
import Sidebar from "@/components/Sidebar";
import * as api from "@/lib/api";
import { isApiError, toastApiError } from "@/lib/errors";
import type { Message } from "@/types";

export default function ChatPage() {
  const router = useRouter();
  const { username, loading, logout, mustChangePassword } = useAuth();
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [sessionRefreshKey, setSessionRefreshKey] = useState(0);
  const [configChecked, setConfigChecked] = useState(false);

  const handleMessagesChange = useCallback(
    (msgs: Message[]) => {
      if (currentSessionId && msgs.length > 0) {
        const firstUserMsg = msgs.find((m) => m.role === "user");
        const title = firstUserMsg?.text?.slice(0, 50) || "New Chat";
        api.saveSession(currentSessionId, title, msgs).catch((err: unknown) => {
          // Don't interrupt the voice flow with a modal; a toast is enough.
          toastApiError(err, "Failed to save chat history.");
        });
      }
    },
    [currentSessionId]
  );

  const handleGreetingDone = useCallback(() => {
    // Mic is now manual - user clicks the mic button to start
  }, []);

  const realtime = useRealtimeAudio({
    onMessagesChange: handleMessagesChange,
    onGreetingDone: handleGreetingDone,
  });

  const realtimeRef = useRef(realtime);
  useEffect(() => {
    realtimeRef.current = realtime;
  }, [realtime]);

  useEffect(() => {
    if (loading) return;
    if (!username) {
      router.replace("/login");
      return;
    }
    if (mustChangePassword) {
      router.replace("/change-password?forced=1");
      return;
    }

    api
      .getSettingsStatus()
      .then((data) => {
        if (!data.initialized) {
          router.replace("/settings/cluster");
        } else {
          setConfigChecked(true);
        }
      })
      .catch(() => {
        router.replace("/settings/cluster");
      });
  }, [loading, username, mustChangePassword, router]);

  const handleStartConversation = useCallback(() => {
    void realtimeRef.current?.connect();
  }, []);

  const handleNewChat = useCallback(() => {
    realtime.disconnect();
    const id = crypto.randomUUID();
    setCurrentSessionId(id);
    realtime.clearMessages();
    setSessionRefreshKey((k) => k + 1);
  }, [realtime]);

  const handleLoadSession = useCallback(
    async (sessionId: string) => {
      try {
        const session = await api.loadSession(sessionId);
        setCurrentSessionId(sessionId);
        realtime.setMessages(
          session.messages.map((m) => ({
            role: m.role as "user" | "assistant",
            text: m.text,
          }))
        );
      } catch (err) {
        if (isApiError(err) && err.status === 401) {
          router.replace("/login");
          return;
        }
        toastApiError(err, "Failed to load chat session.");
      }
    },
    [realtime, router]
  );

  const handleDeleteSession = useCallback(
    async (sessionId: string) => {
      try {
        await api.deleteSession(sessionId);
        if (currentSessionId === sessionId) {
          handleNewChat();
        }
        setSessionRefreshKey((k) => k + 1);
      } catch (err) {
        if (isApiError(err) && err.status === 401) {
          router.replace("/login");
          return;
        }
        toastApiError(err, "Failed to delete chat session.");
      }
    },
    [currentSessionId, handleNewChat, router]
  );

  const handleLogout = useCallback(async () => {
    realtime.disconnect();
    await logout();
    router.replace("/login");
  }, [realtime, logout, router]);

  const handleOpenClusterSettings = useCallback(() => {
    router.push("/settings/cluster");
  }, [router]);

  const handleOpenChangePassword = useCallback(() => {
    router.push("/change-password");
  }, [router]);

  useEffect(() => {
    if (!currentSessionId && username) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCurrentSessionId(crypto.randomUUID());
    }
  }, [currentSessionId, username]);

  if (loading || !username || !configChecked) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0a0a0a]">
        <div className="text-gray-400">Loading...</div>
      </div>
    );
  }

  return (
    <div className="flex h-screen">
      <Sidebar
        username={username}
        currentSessionId={currentSessionId}
        sessionRefreshKey={sessionRefreshKey}
        onNewChat={handleNewChat}
        onLoadSession={(id) => {
          void handleLoadSession(id);
        }}
        onDeleteSession={(id) => {
          void handleDeleteSession(id);
        }}
        onLogout={() => {
          void handleLogout();
        }}
        onDocumentsChange={() => setSessionRefreshKey((k) => k + 1)}
        onOpenSettings={handleOpenClusterSettings}
        onOpenChangePassword={handleOpenChangePassword}
      />
      <main className="flex flex-1 flex-col">
        <ChatInterface
          messages={realtime.messages}
          status={realtime.status}
          isConnected={realtime.isConnected}
          isRecording={realtime.isRecording}
          audioLevel={realtime.audioLevel}
          userTranscript={realtime.userTranscript}
          assistantTranscript={realtime.assistantTranscript}
          onStartConversation={handleStartConversation}
          onStartRecording={() => {
            void realtime.startRecording();
          }}
          onStopRecording={realtime.stopRecording}
          onSendText={realtime.sendText}
        />
      </main>
    </div>
  );
}
