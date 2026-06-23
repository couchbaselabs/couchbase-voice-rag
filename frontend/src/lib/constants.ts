const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const API_BASE = `${API_URL}/api`;
export const WS_BASE = `${API_URL.replace(/^http/, "ws")}/ws`;
