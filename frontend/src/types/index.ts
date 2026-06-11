import type { components } from "./api";

// UI-only state types (no API boundary).
export interface Message {
  role: "user" | "assistant";
  text: string;
}

export type ConnectionStatus =
  | "idle"
  | "connecting"
  | "connected"
  | "listening"
  | "processing"
  | "searching"
  | "searching_web"
  | "responding"
  | "error";

// API-boundary types — aliased from the generated OpenAPI schema so the
// frontend breaks at compile time when the backend adds/removes fields.
export type ChatSession = components["schemas"]["ChatSessionSummary"];
export type UploadedFile = components["schemas"]["DocumentSummary"];
