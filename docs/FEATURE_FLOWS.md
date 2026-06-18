# Feature Flows — Couchbase Voice RAG

This document describes every user-facing feature flow in detail, intended as a reference for Playwright E2E test case creation.

---

## Table of Contents

1. [Login](#1-login)
2. [Settings Configuration](#2-settings-configuration)
3. [Logout](#3-logout)
4. [File Upload & Vectorization](#4-file-upload--vectorization)
5. [Chat Session Management](#5-chat-session-management)
6. [Chat Connection & Initialization](#6-chat-connection--initialization)
7. [Voice Input (Speech-to-Text)](#7-voice-input-speech-to-text)
8. [Text Input](#8-text-input)
9. [AI Response & Function Calling](#9-ai-response--function-calling)
10. [Session Expiration & Error States](#10-session-expiration--error-states)
11. [API Endpoints](#11-api-endpoints)
12. [WebSocket Messages](#12-websocket-messages)
13. [UI Elements Inventory](#13-ui-elements-inventory)
14. [Edge Cases](#14-edge-cases)

---

## 1. Login

### Preconditions
- User not logged in (no valid token in localStorage)

### Flow

| Step | User Action | Expected Result |
|------|-------------|-----------------|
| 1 | Navigate to `/login` | Login form renders: username input, password input, "Login" button |
| 2 | Enter username and password | Fields populated |
| 3 | Click "Login" | Button text → "Logging in...", button disabled |
| 4a | Valid credentials | Token stored in localStorage, cookie set (samesite=none, httponly, secure, 24h), redirect to `/chat` |
| 4b | Invalid credentials | Error message in red below form, button re-enabled |

### API
- `POST /api/auth/login` — `{username, password}` → `{token, username}` or 401

### UI Elements
- Username input (required)
- Password input (required, type=password)
- Submit button ("Login" / "Logging in...")
- Error message (red text, hidden initially)
- Couchbase logo + title "Couchbase Voice RAG"

---

## 2. Settings Configuration

### Preconditions
- User logged in, on `/chat` page
- First login: settings not initialized → modal auto-opens

### Flow

| Step | User Action | Expected Result |
|------|-------------|-----------------|
| 1 | Page loads | `GET /api/settings/status` called |
| 2a | `initialized: false` | SettingsForm modal opens automatically |
| 2b | `initialized: true` | Chat interface ready |
| 3 | Fill connection fields | Connection String, Username, Password, Bucket Name required |
| 4 | Click "Connect & Initialize" | Button → "Connecting to Couchbase...", disabled |
| 5a | Connection success | Modal closes, chat available. `{ok: true}` |
| 5b | Connection failure | Error message in red, form stays open |

### Post-Initialization Access
- Click "Couchbase Cluster Settings" button at bottom of sidebar
- Same form, but "Cancel" button available

### API
- `GET /api/settings/status` → `{initialized: bool}`
- `GET /api/settings` → `{settings: Record<string, string>}` (password masked)
- `POST /api/settings` → `{ok: bool, message: string}`

### Form Fields
| Field | Required | Placeholder |
|-------|----------|-------------|
| Connection String | Yes | `couchbase://localhost` or `couchbases://cb.xxx.cloud.couchbase.com` |
| Username | Yes | - |
| Password | Yes | (eye toggle for show/hide) |
| Bucket Name | Yes | `realtime-rag` |
| Scope Name | No | `_default` |
| Collection Name | No | `documents` |
| Search Index Name | No | `vector-search-index` |

---

## 3. Logout

### Normal Logout
| Step | User Action | Expected Result |
|------|-------------|-----------------|
| 1 | Click "Logout" in sidebar | WebSocket disconnected, `POST /api/auth/logout`, localStorage cleared, redirect to `/login` |

### Force Logout (from Settings)
| Step | User Action | Expected Result |
|------|-------------|-----------------|
| 1 | Click "Force Logout All Sessions" | All active tokens invalidated, all users logged out |

### API
- `POST /api/auth/logout` → `{ok: true}`
- `POST /api/auth/force-logout` → `{ok: true, message: "All tokens invalidated"}`

---

## 4. File Upload & Vectorization

### Preconditions
- Logged in, settings initialized

### Upload Flow

| Step | User Action | Expected Result |
|------|-------------|-----------------|
| 1 | Click "Upload PDF / DOCX / TXT" | File browser opens |
| 2 | Select file | Accepted: `.pdf`, `.docx`, `.txt`. Max 50MB |
| 3 | File uploading | Spinner + "Uploading & chunking..." |
| 4 | Upload response | File appears in list immediately with "Vectorizing..." (yellow, pulsing) |
| 5 | Background vectorization | Polling `GET /api/documents/status/{filename}` every 3s |
| 6 | Vectorization complete | Status changes to "AI Workflow: {id}" or "Local embedding" |

### File List Display
Each file shows:
- Filename (truncated if long)
- `{chunk_count} chunks`
- Status badge:
  - `Vectorizing...` — yellow, pulsing animation
  - `AI Workflow: {workflow_id}` — Capella vectorization
  - `Local embedding` — Python embedding fallback
- Delete button (trash icon)

### Delete Flow
| Step | User Action | Expected Result |
|------|-------------|-----------------|
| 1 | Click trash icon | Button disabled |
| 2 | API response | File removed from list, `{ok: true}` |

### Error Cases
| Scenario | Message |
|----------|---------|
| Wrong file type | "Supported file types: .pdf, .docx, .txt" |
| File too large | "File too large. Maximum size is 50MB." |
| Network error | Red error text below upload area |

### API
- `POST /api/documents/upload` → `{filename, chunk_count, status: "vectorizing"}`
- `GET /api/documents/status/{filename}` → `{status, chunk_count?, method?, error?}`
- `GET /api/documents` → `UploadedFile[]`
- `DELETE /api/documents/{filename}` → `{ok: true}`

---

## 5. Chat Session Management

### Session List
- Loaded on page mount: `GET /api/chat/sessions`
- Displayed in "Chat History" section of sidebar
- Each entry: title + date, with delete (×) button

### New Chat
| Step | User Action | Expected Result |
|------|-------------|-----------------|
| 1 | Click "New Chat" | WebSocket disconnected, messages cleared, new session ID generated |
| 2 | Chat interface empty | "Start Conversation" button shown |

### Load Session
| Step | User Action | Expected Result |
|------|-------------|-----------------|
| 1 | Click session in history | `GET /api/chat/sessions/{id}`, messages loaded into chat |

### Auto-Save
- Messages saved automatically when they change
- Title: first user message (truncated to 50 chars)
- `POST /api/chat/sessions/{id}` with `{title, messages}`

### Delete Session
| Step | User Action | Expected Result |
|------|-------------|-----------------|
| 1 | Click × on session | `DELETE /api/chat/sessions/{id}` |
| 2 | If current session | Auto-creates new empty session |

### API
- `GET /api/chat/sessions` → `ChatSession[]`
- `GET /api/chat/sessions/{id}` → `{session_id, title, messages}`
- `POST /api/chat/sessions/{id}` → `{ok: true}`
- `DELETE /api/chat/sessions/{id}` → `{ok: true}`

---

## 6. Chat Connection & Initialization

### Preconditions
- Logged in, settings initialized, on empty chat

### Flow

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Start Conversation" | Status: `connecting` |
| 2 | WebSocket connections | OpenAI Realtime WS + Deepgram STT WS opened |
| 3 | Token verified | Backend validates JWT on both WS connections |
| 4 | Microphone permission | Browser prompts for mic access |
| 5 | OpenAI session configured | `turn_detection: null`, tools: `search_knowledge_base` + `search_web` |
| 6 | Greeting sent | AI speaks: "Hello! I am Couchbase Voice RAG Agent. How can I help you today?" |
| 7 | Greeting plays | Audio plays, transcript appears |
| 8 | Ready | Status: `connected`, mic button green "Ready" |

### Deepgram Setup
- URL params: `language=en`, `model=nova-2`, `punctuate=true`, `interim_results=true`, `utterance_end_ms=1500`
- Keywords from Knowledge Base vocabulary (up to 20 terms, boosted 2×)
- Keepalive: `{"type": "KeepAlive"}` every 8 seconds

### Mic Pre-Initialization
- Microphone + AudioWorklet initialized on Deepgram `onopen`
- No delay when user clicks record button
- Audio: 24kHz, mono, echoCancellation + noiseSuppression

---

## 7. Voice Input (Speech-to-Text)

### Preconditions
- Status: `connected`, mic initialized

### Flow

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click mic button | Status: `listening`, button yellow pulsing |
| 2 | User speaks | Audio streamed to Deepgram only (NOT OpenAI) |
| 3 | Interim transcript | Real-time transcript shown in red bubble |
| 4 | Silence detected (1.5s) | Deepgram sends `UtteranceEnd`, auto-submits |
| 5 | OR click mic again | Manual stop, transcript submitted |
| 6 | Transcript sent | `text.send` to OpenAI via WS, status: `processing` |

### Audio Flow
```
Mic → AudioWorklet (24kHz PCM16) → Deepgram WS (binary)
                                         ↓
                               Transcript (interim/final)
                                         ↓
                        Accumulated final text → OpenAI (text.send)
```

### Key Behaviors
- Audio NOT sent to OpenAI (no server_vad, no barge-in conflicts)
- `aiRespondingRef` blocks audio during AI response (no echo loop)
- Volume level visualization via RMS calculation
- Mic button disabled during: `processing`, `searching`, `searching_web`, `responding`

---

## 8. Text Input

### Preconditions
- Status: `connected`

### Flow

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Type in text field | Characters appear in input |
| 2 | Click "Send" or press Enter | Message appears in chat (red, right-aligned) |
| 3 | Status → `processing` | Input disabled, mic disabled |
| 4 | Backend relay | `conversation.item.create` + `response.create` sent to OpenAI |

---

## 9. AI Response & Function Calling

### Response WITHOUT Tool Calls

| Event | UI Change |
|-------|-----------|
| `text.delta` | Assistant transcript builds incrementally |
| `audio.delta` | Status: `responding`, audio queued and played |
| `text.done` | Full message added to chat, transcript cleared |
| Audio queue empty | Status: `connected` (Ready) |

### Response WITH Knowledge Base Search

| Event | UI Change |
|-------|-----------|
| `function_call.searching` (source: `kb`) | Status: `searching`, "Searching knowledge base..." |
| Backend: embed query → vector search (top 3) | - |
| `function_call.results` (source: `kb`) | - |
| AI generates response with KB context | `audio.delta` / `text.delta` stream |
| `text.done` / audio complete | Status: `connected` |

### Response WITH Web Search Fallback

| Event | UI Change |
|-------|-----------|
| KB search returns no results | OpenAI decides to call `search_web` |
| `function_call.searching` (source: `web`) | Status: `searching_web`, "Searching the web..." |
| Backend: Tavily API search | - |
| `function_call.results` (source: `web`) | - |
| AI generates response with web context | Response prefixed with "I found this from a web search..." |

### System Prompt Behavior
- **KB has results**: "Based on the knowledge base..."
- **KB empty, web used**: "I found this from a web search... For more accurate answers, you can upload relevant documents."
- **Both fail**: General knowledge answer

---

## 10. Session Expiration & Error States

### Connection Status States

| Status | Voice Button Text | Mic Enabled |
|--------|-------------------|-------------|
| `idle` | Disconnected | No |
| `connecting` | Connecting... | No |
| `connected` | Ready | Yes |
| `listening` | Listening... | Yes (recording) |
| `processing` | Processing... | No |
| `searching` | Searching knowledge base... | No |
| `searching_web` | Searching the web... | No |
| `responding` | Responding... | No |
| `error` | Error | No |

### Session Expiration (30 min)
- OpenAI error: `session_expired`
- UI: System message "Session expired (30 min limit). Please click New Chat to continue."
- Status: `idle`

### Non-Fatal Errors (Ignored)
- `input_audio_buffer_commit_empty`
- `response_cancel_not_active`

### Fatal Errors
- Any other OpenAI error → Status: `connected` (recovers for retry)
- WebSocket disconnect → Status: `idle`

---

## 11. API Endpoints

### Authentication
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/login` | Login |
| POST | `/api/auth/logout` | Logout |
| GET | `/api/auth/me` | Current user |
| POST | `/api/auth/force-logout` | Invalidate all tokens |

### Documents
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/documents` | List files |
| POST | `/api/documents/upload` | Upload file (async vectorization) |
| GET | `/api/documents/status/{filename}` | Vectorization status |
| DELETE | `/api/documents/{filename}` | Delete file |

### Chat Sessions
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/chat/sessions` | List sessions |
| GET | `/api/chat/sessions/{id}` | Load session |
| POST | `/api/chat/sessions/{id}` | Save session |
| DELETE | `/api/chat/sessions/{id}` | Delete session |

### Settings
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/settings/status` | Check initialized |
| GET | `/api/settings` | Get settings |
| POST | `/api/settings` | Save settings |

### WebSockets
| Path | Description |
|------|-------------|
| `WS /ws/realtime?token={jwt}` | OpenAI Realtime relay |
| `WS /ws/deepgram?token={jwt}` | Deepgram STT relay |

---

## 12. WebSocket Messages

### Client → Server (`/ws/realtime`)
```
text.send        {type, text}           Send text message to AI
response.cancel  {type}                 Cancel AI response (barge-in)
session.config   {type, instructions?, voice?}  Update session
```

### Server → Client (`/ws/realtime`)
```
audio.delta              {type, audio}                    Audio chunk (base64 PCM16)
audio.done               {type}                           Audio complete
transcript.partial       {type, text}                     Streaming assistant text
transcript.done          {type, text, role}                Final transcript
text.delta               {type, text}                     Text response chunk
text.done                {type, text}                     Text response complete
function_call.searching  {type, query, source: "kb"|"web"} Search started
function_call.results    {type, source, count, error?}     Search completed
session_expired          {type, message}                   30-min limit reached
error                    {type, message}                   Error occurred
```

### Client → Server (`/ws/deepgram`)
```
Binary PCM16 audio data (raw bytes, 24kHz mono)
```

### Server → Client (`/ws/deepgram`)
```
{transcript: string, is_final: boolean}   STT result
{type: "utterance_end"}                    Silence detected
```

---

## 13. UI Elements Inventory

### Login Page
- Couchbase logo
- Title: "Couchbase Voice RAG"
- Username input
- Password input
- "Login" button
- Error message area

### Chat Page — Sidebar
- Logo + title
- "Logged in as {username}"
- "New Chat" button (red)
- "Logout" button (gray)
- **Knowledge Base** section: file list + upload button
- **Chat History** section: session list
- "Couchbase Cluster Settings" button
- Deploy timestamp

### Chat Page — Main Area
- Header: "Chat (Powered by Capella AI Services)"
- Message area (scrollable, auto-scroll)
  - User messages: red background, right-aligned
  - Assistant messages: dark gray background, left-aligned
  - Live transcript: semi-transparent
  - Status indicator: spinner + status text
- Input area:
  - Text input field
  - "Send" button
  - Voice button (VoiceButton component)
- Initial state: "Start Conversation" play button

### Voice Button States
| State | Color | Icon | Animation |
|-------|-------|------|-----------|
| Disconnected | Gray | Mic | None |
| Ready | Green (#6aa36f) | Mic | None |
| Listening | Yellow (#e8b62c) | Stop square | Pulse |
| Disabled | Gray (50% opacity) | Mic | None |

---

## 14. Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| Mic permission denied | Connection continues, recording silently fails, text input still works |
| Upload during vectorization | Multiple files can vectorize concurrently, each polled independently |
| Delete current session | Auto-creates new empty session |
| Rapid text sends | Each triggers separate response, all saved to history |
| Browser tab inactive | AudioContext suspended, auto-resumed on next playback |
| Network disconnect mid-recording | Silent failure, no error shown |
| Settings with masked password | Backend uses previously saved password |
| 401 during API call | Error logged, no auto re-login |
| Deepgram WS disconnect | Keepalive prevents this; if happens, STT stops silently |
| Large PDF upload (>50MB) | "File too large" error before upload starts |
| Empty voice input (no speech) | `stopRecording` with empty transcript → status returns to `connected` |
