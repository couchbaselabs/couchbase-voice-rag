"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { WS_BASE } from "@/lib/constants";
import type { Message, ConnectionStatus } from "@/types";

const SAMPLE_RATE = 24000;

interface UseRealtimeAudioOptions {
  onMessagesChange?: (messages: Message[]) => void;
  onGreetingDone?: () => void;
}

export function useRealtimeAudio({ onMessagesChange, onGreetingDone }: UseRealtimeAudioOptions) {
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [messages, setMessages] = useState<Message[]>([]);
  const [userTranscript, setUserTranscript] = useState("");
  const [assistantTranscript, setAssistantTranscript] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const dgWsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const isRecordingRef = useRef(false);
  const audioQueueRef = useRef<Float32Array[]>([]);
  const isPlayingRef = useRef(false);
  const messagesRef = useRef<Message[]>([]);
  const greetingDoneRef = useRef(false);
  const onGreetingDoneRef = useRef(onGreetingDone);
  const stopRecordingRef = useRef<() => void>(() => {});
  const responseDoneRef = useRef(false);
  const aiRespondingRef = useRef(false);
  const dgTranscriptRef = useRef("");
  const micReadyRef = useRef(false);

  // Keep refs in sync
  useEffect(() => {
    onGreetingDoneRef.current = onGreetingDone;
  }, [onGreetingDone]);

  useEffect(() => {
    messagesRef.current = messages;
    onMessagesChange?.(messages);
  }, [messages, onMessagesChange]);

  const playNextAudioChunk = useCallback(function playNext(): void {
    if (audioQueueRef.current.length === 0) {
      isPlayingRef.current = false;
      if (!greetingDoneRef.current) {
        greetingDoneRef.current = true;
        onGreetingDoneRef.current?.();
      }
      // Audio playback finished — now safe to accept input
      if (responseDoneRef.current) {
        responseDoneRef.current = false;
        aiRespondingRef.current = false;
        setStatus("connected");
      }
      return;
    }

    isPlayingRef.current = true;
    const chunk = audioQueueRef.current.shift()!;
    const ctx = audioContextRef.current;
    if (!ctx) return;

    // Resume AudioContext if suspended (browser autoplay policy)
    if (ctx.state === "suspended") {
      void ctx.resume();
    }

    const buffer = ctx.createBuffer(1, chunk.length, SAMPLE_RATE);
    buffer.copyToChannel(new Float32Array(chunk.buffer) as unknown as Float32Array<ArrayBuffer>, 0);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    source.onended = () => playNext();
    source.start();
  }, []);

  const enqueueAudio = useCallback(
    (base64: string) => {
      const binary = atob(base64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
      }
      const int16 = new Int16Array(bytes.buffer);
      const float32 = Float32Array.from(int16, (v) => v / 32768);
      audioQueueRef.current.push(float32);
      if (!isPlayingRef.current) {
        playNextAudioChunk();
      }
    },
    [playNextAudioChunk]
  );

  // Send final Deepgram transcript to OpenAI as text
  const sendVoiceText = useCallback((text: string) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || !text.trim()) return;

    setMessages((prev) => [...prev, { role: "user", text: text.trim() }]);
    setUserTranscript("");
    dgTranscriptRef.current = "";
    ws.send(JSON.stringify({ type: "text.send", text: text.trim() }));
    setStatus("processing");
    aiRespondingRef.current = true;
  }, []);

  const connect = useCallback(async () => {
    setStatus("connecting");

    const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
    audioContextRef.current = ctx;

    // The backend authenticates the WebSocket from the httpOnly `token`
    // cookie, which the browser attaches automatically because the
    // Next.js rewrite proxies /ws/* to the backend under the same origin.
    const ws = new WebSocket(`${WS_BASE}/realtime`);
    wsRef.current = ws;

    const dgWs = new WebSocket(`${WS_BASE}/deepgram`);
    dgWsRef.current = dgWs;

    dgWs.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "utterance_end") {
        // Deepgram detected end of speech — auto-submit
        if (isRecordingRef.current && dgTranscriptRef.current.trim()) {
          stopRecordingRef.current();
        }
        return;
      }
      if (data.transcript) {
        if (data.is_final) {
          dgTranscriptRef.current += (dgTranscriptRef.current ? " " : "") + data.transcript;
          setUserTranscript(dgTranscriptRef.current);
        } else {
          // Show interim results
          setUserTranscript(
            dgTranscriptRef.current + (dgTranscriptRef.current ? " " : "") + data.transcript
          );
        }
      }
    };

    dgWs.onopen = async () => {
      // Pre-initialize microphone so startRecording has zero latency
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            sampleRate: SAMPLE_RATE,
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
          },
        });
        mediaStreamRef.current = stream;

        const processorCode = `
          class PCMProcessor extends AudioWorkletProcessor {
            constructor() { super(); this.buffer = []; }
            process(inputs) {
              const input = inputs[0];
              if (input.length > 0) {
                const samples = input[0];
                const ratio = sampleRate / 24000;
                for (let i = 0; i < samples.length; i += ratio) {
                  const idx = Math.floor(i);
                  if (idx < samples.length) this.buffer.push(samples[idx]);
                }
                if (this.buffer.length >= 2400) {
                  let sumSquares = 0;
                  for (let i = 0; i < this.buffer.length; i++) sumSquares += this.buffer[i] * this.buffer[i];
                  const rms = Math.sqrt(sumSquares / this.buffer.length);
                  const int16 = new Int16Array(this.buffer.length);
                  for (let i = 0; i < this.buffer.length; i++) int16[i] = Math.max(-32768, Math.min(32767, Math.floor(this.buffer[i] * 32768)));
                  this.port.postMessage({ type: 'audio', buffer: int16.buffer }, [int16.buffer]);
                  this.port.postMessage({ type: 'volume', level: rms });
                  this.buffer = [];
                }
              }
              return true;
            }
          }
          registerProcessor('pcm-processor', PCMProcessor);
        `;
        const blob = new Blob([processorCode], { type: "application/javascript" });
        const url = URL.createObjectURL(blob);
        await ctx.audioWorklet.addModule(url);
        URL.revokeObjectURL(url);

        const source = ctx.createMediaStreamSource(stream);
        const worklet = new AudioWorkletNode(ctx, "pcm-processor");
        workletNodeRef.current = worklet;

        worklet.port.onmessage = (e) => {
          const msg = e.data;
          if (msg.type === "volume") {
            setAudioLevel(isRecordingRef.current ? Math.min(1, msg.level / 0.15) : 0);
            return;
          }
          if (msg.type === "audio" && isRecordingRef.current && !aiRespondingRef.current) {
            const dg = dgWsRef.current;
            if (dg && dg.readyState === WebSocket.OPEN) {
              dg.send(msg.buffer as ArrayBuffer);
            }
          }
        };

        source.connect(worklet);
        worklet.connect(ctx.destination);
        micReadyRef.current = true;
      } catch (err) {
        console.error("Failed to init microphone:", err);
      }
    };

    dgWs.onerror = () => {
      console.warn("Deepgram STT connection failed");
      dgWsRef.current = null;
    };

    ws.onopen = () => {
      setStatus("connected");
    };

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);

      switch (msg.type) {
        case "audio.delta":
          aiRespondingRef.current = true;
          setStatus("responding");
          enqueueAudio(msg.audio);
          break;

        case "audio.done":
          // Audio playback will finish asynchronously
          break;

        case "transcript.partial":
          setAssistantTranscript((prev) => prev + msg.text);
          break;

        case "transcript.done":
          if (msg.role === "assistant") {
            setAssistantTranscript("");
            if (msg.text) {
              setMessages((prev) => [...prev, { role: "assistant", text: msg.text }]);
            }
            if (isPlayingRef.current) {
              responseDoneRef.current = true;
            } else {
              aiRespondingRef.current = false;
              setStatus("connected");
            }
          }
          break;

        case "text.delta":
          setAssistantTranscript((prev) => prev + msg.text);
          break;

        case "text.done":
          setAssistantTranscript("");
          if (msg.text) {
            setMessages((prev) => [...prev, { role: "assistant", text: msg.text }]);
          }
          if (isPlayingRef.current) {
            responseDoneRef.current = true;
          } else {
            aiRespondingRef.current = false;
            setStatus("connected");
          }
          break;

        case "function_call.searching":
          aiRespondingRef.current = true;
          setStatus(msg.source === "web" ? "searching_web" : "searching");
          break;

        case "function_call.results":
          // Will transition to responding when audio starts
          break;

        case "session_expired":
          console.warn("Session expired:", msg.message);
          setMessages((prev) => [
            ...prev,
            {
              role: "assistant",
              text: "Session expired (30 min limit). Please click New Chat to continue.",
            },
          ]);
          setStatus("idle");
          break;

        case "error":
          console.error("Server error:", msg.message);
          aiRespondingRef.current = false;
          setStatus("connected");
          break;
      }
    };

    ws.onclose = () => {
      setStatus("idle");
      wsRef.current = null;
    };

    ws.onerror = () => {
      setStatus("error");
    };
  }, [enqueueAudio]);

  const disconnect = useCallback(() => {
    if (workletNodeRef.current) {
      workletNodeRef.current.disconnect();
      workletNodeRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((t) => t.stop());
      mediaStreamRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (dgWsRef.current) {
      dgWsRef.current.close();
      dgWsRef.current = null;
    }
    if (audioContextRef.current) {
      void audioContextRef.current.close();
      audioContextRef.current = null;
    }
    isRecordingRef.current = false;
    micReadyRef.current = false;
    setIsRecording(false);
    setAudioLevel(0);
    audioQueueRef.current = [];
    isPlayingRef.current = false;
    greetingDoneRef.current = false;
    dgTranscriptRef.current = "";
    setStatus("idle");
  }, []);

  const interruptPlayback = useCallback(() => {
    audioQueueRef.current = [];
    isPlayingRef.current = false;

    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "response.cancel" }));
    }

    setAssistantTranscript("");
    aiRespondingRef.current = false;
    setStatus("connected");
  }, []);

  const startRecording = useCallback(async () => {
    if (!micReadyRef.current) return;

    if (isPlayingRef.current) {
      interruptPlayback();
    }

    dgTranscriptRef.current = "";
    setUserTranscript("");
    isRecordingRef.current = true;
    setIsRecording(true);
    setStatus("listening");
  }, [interruptPlayback]);

  const stopRecording = useCallback(() => {
    if (!isRecordingRef.current) return;

    isRecordingRef.current = false;
    setIsRecording(false);
    setAudioLevel(0);

    const text = dgTranscriptRef.current.trim();
    if (text) {
      sendVoiceText(text);
    } else {
      setStatus("connected");
    }
  }, [sendVoiceText]);

  // Keep stopRecordingRef in sync
  useEffect(() => {
    stopRecordingRef.current = stopRecording;
  }, [stopRecording]);

  const sendText = useCallback((text: string) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;

    setMessages((prev) => [...prev, { role: "user", text }]);
    ws.send(JSON.stringify({ type: "text.send", text }));
    setStatus("processing");
    aiRespondingRef.current = true;
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setUserTranscript("");
    setAssistantTranscript("");
    dgTranscriptRef.current = "";
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  return {
    status,
    messages,
    userTranscript,
    assistantTranscript,
    connect,
    disconnect,
    startRecording,
    stopRecording,
    sendText,
    setMessages,
    clearMessages,
    isConnected: status !== "idle" && status !== "error" && status !== "connecting",
    isRecording,
    audioLevel,
  };
}
