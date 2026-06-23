import type { components } from "@/types/api";

import { API_BASE } from "./constants";

type Schemas = components["schemas"];

type LoginRequest = Schemas["LoginRequest"];
type LoginResponse = Schemas["LoginResponse"];
type ChangePasswordRequest = Schemas["ChangePasswordRequest"];
type MeResponse = Schemas["MeResponse"];
type ForceLogoutResponse = Schemas["ForceLogoutResponse"];
type OkMessageResponse = Schemas["OkMessageResponse"];
type OkResponse = Schemas["OkResponse"];
type DocumentSummary = Schemas["DocumentSummary"];
type UploadResponse = Schemas["UploadResponse"];
type JobStatusResponse = Schemas["JobStatusResponse"];
type ChatSessionSummary = Schemas["ChatSessionSummary"];
type ChatSessionDetail = Schemas["ChatSessionDetail"];
type SaveSessionRequest = Schemas["SaveSessionRequest"];
type SettingsRequest = Schemas["SettingsRequest"];
type SettingsResponse = Schemas["SettingsResponse"];
type SettingsStatusResponse = Schemas["SettingsStatusResponse"];
type SettingsProgressResponse = Schemas["SettingsProgressResponse"];
type SaveSettingsResponse = Schemas["SaveSettingsResponse"];

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly requestId: string | undefined;

  constructor(status: number, detail: string, requestId: string | undefined) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.requestId = requestId;
  }
}

function readRequestId(res: Response): string | undefined {
  return res.headers.get("x-request-id") ?? undefined;
}

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    credentials: "include",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new ApiError(res.status, body.detail ?? res.statusText, readRequestId(res));
  }
  return res.json() as Promise<T>;
}

// Auth
export async function login(username: string, password: string): Promise<LoginResponse> {
  const req: LoginRequest = { username, password };
  return fetchJSON<LoginResponse>(`${API_BASE}/auth/login`, {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function logout(): Promise<void> {
  await fetchJSON<OkMessageResponse>(`${API_BASE}/auth/logout`, { method: "POST" });
}

export async function forceLogout(): Promise<ForceLogoutResponse> {
  return fetchJSON<ForceLogoutResponse>(`${API_BASE}/auth/force-logout`, { method: "POST" });
}

export async function changePassword(
  currentPassword: string,
  newPassword: string
): Promise<OkMessageResponse> {
  const req: ChangePasswordRequest = {
    current_password: currentPassword,
    new_password: newPassword,
  };
  return fetchJSON<OkMessageResponse>(`${API_BASE}/auth/change-password`, {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function getMe(): Promise<MeResponse> {
  return fetchJSON<MeResponse>(`${API_BASE}/auth/me`);
}

// Documents
export async function listDocuments(): Promise<DocumentSummary[]> {
  return fetchJSON<DocumentSummary[]>(`${API_BASE}/documents`);
}

export async function uploadDocument(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/documents/upload`, {
    method: "POST",
    credentials: "include",
    body: formData,
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new ApiError(res.status, body.detail ?? res.statusText, readRequestId(res));
  }
  return res.json() as Promise<UploadResponse>;
}

export async function getUploadStatus(filename: string): Promise<JobStatusResponse> {
  return fetchJSON<JobStatusResponse>(
    `${API_BASE}/documents/status/${encodeURIComponent(filename)}`
  );
}

export async function deleteDocument(filename: string): Promise<void> {
  await fetchJSON<OkResponse>(`${API_BASE}/documents/${encodeURIComponent(filename)}`, {
    method: "DELETE",
  });
}

// Chat sessions
export async function listSessions(): Promise<ChatSessionSummary[]> {
  return fetchJSON<ChatSessionSummary[]>(`${API_BASE}/chat/sessions`);
}

export async function loadSession(sessionId: string): Promise<ChatSessionDetail> {
  return fetchJSON<ChatSessionDetail>(`${API_BASE}/chat/sessions/${sessionId}`);
}

export async function saveSession(
  sessionId: string,
  title: string,
  messages: SaveSessionRequest["messages"]
): Promise<void> {
  const req: SaveSessionRequest = { title, messages };
  await fetchJSON<OkResponse>(`${API_BASE}/chat/sessions/${sessionId}`, {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function deleteSession(sessionId: string): Promise<void> {
  await fetchJSON<OkResponse>(`${API_BASE}/chat/sessions/${sessionId}`, {
    method: "DELETE",
  });
}

// Settings
export async function getSettingsStatus(): Promise<SettingsStatusResponse> {
  return fetchJSON<SettingsStatusResponse>(`${API_BASE}/settings/status`);
}

export async function getSettingsProgress(): Promise<SettingsProgressResponse> {
  return fetchJSON<SettingsProgressResponse>(`${API_BASE}/settings/progress`);
}

export async function getSettings(): Promise<SettingsResponse> {
  return fetchJSON<SettingsResponse>(`${API_BASE}/settings`);
}

export async function saveSettings(settings: SettingsRequest): Promise<SaveSettingsResponse> {
  return fetchJSON<SaveSettingsResponse>(`${API_BASE}/settings`, {
    method: "POST",
    body: JSON.stringify(settings),
  });
}
