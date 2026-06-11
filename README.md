# Couchbase Realtime Voice RAG

A real-time voice and text Retrieval-Augmented Generation (RAG) application powered by **Azure OpenAI Realtime API** and **Couchbase Vector Search**. Upload PDF documents to build a knowledge base, then ask questions via voice or text and receive AI-generated answers grounded in your documents.

## Architecture

```
                        +---------------------+
                        |       Browser       |
                        +----------+----------+
                                   |
                            HTTPS / WebSocket
                                   |
                    +--------------+---------------+
                    |  Azure Container Apps (TLS)   |
                    +----+--------------------+----+
                         |                    |
                    /api/* /ws/*              /*
                         |                    |
                +--------+---+        +------+--------+
                |  FastAPI   |        |  Next.js      |
                |  Backend   |        |  Frontend     |
                |  :8000     |        |  :3000        |
                +--+---+---+-+        +---------------+
                   |   |   |
      +------------+   |   +-------------+
      |                |                 |
+-----+----------+ +--+------------+ +--+---------------+
| Azure OpenAI   | | Azure OpenAI  | | Couchbase        |
| Realtime API   | | Embeddings    | | (Vector Search   |
| (Voice + LLM)  | | (1536-d)      | |  + Storage)      |
+----------------+ +------+--------+ +------------------+
                          |
                   +------+--------+
                   | Deepgram STT  |
                   | (primary)     |
                   +---------------+
```

### Deployment Architecture (Azure Container Apps)

The application runs as two Container Apps in a shared environment:

| Container App | Role | Port |
|---------------|------|------|
| **Frontend** | Next.js (standalone mode), proxies API/WS to backend | 3000 |
| **Backend** | FastAPI + Uvicorn | 8000 |

Next.js rewrites route `/api/*` and `/ws/*` to the backend Container App. Azure Container Apps provides built-in HTTPS/TLS and custom domain support.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 16, React 19, TypeScript (strict + `noUncheckedIndexedAccess` + `exactOptionalPropertyTypes`), Tailwind CSS 4, `sonner` toasts, `ErrorBoundary`, `openapi-typescript` API types, Vitest + RTL + MSW, Playwright + `@axe-core/playwright` |
| Backend | FastAPI, Python 3.13, Gunicorn + Uvicorn workers, `uv` for dependency management, JSON logging + X-Request-ID, slowapi rate limit, cookie-auth WebSocket with Origin allowlist |
| Database | Couchbase 8.0 (vector search, document storage, chat history) |
| AI - Voice | Azure OpenAI Realtime API |
| AI - Embeddings | Azure OpenAI `text-embedding-3-small` (1536 dimensions) |
| AI - STT | Deepgram (required for voice mode — no Whisper fallback) |
| Infrastructure | Docker, Azure Container Apps, ACR |
| Auth | JWT (HS256, 24-hour expiry) |

## Document Processing Pipeline

When a PDF is uploaded, the following pipeline processes it into searchable vector embeddings:

```
+------------+     +----------------+     +---------------+     +------------------+     +------------------+
|  PDF       | --> | Text           | --> | Text Chunking | --> | Batch Embedding  | --> | Store in         |
|  Upload    |     | Extraction     |     | (500 chars,   |     | (text-embedding- |     | Couchbase        |
| (multipart)|     | (pypdf)        |     |  50 overlap)  |     |  3-small, 1536d) |     | (text+vector+    |
+------------+     +----------------+     +---------------+     +------------------+     |  metadata)       |
                                                                                         +-----+------+-----+
                                                                                               |      |
                                                                                               v      v
                                                                                 +-------------+-+ +--+----------------+
                                                                                 | Vocabulary    | | Vector Search     |
                                                                                 | Extraction    | | Index             |
                                                                                 | (acronyms,    | | (dot_product      |
                                                                                 |  CamelCase)   | |  similarity)      |
                                                                                 +---------------+ +-------------------+
```

### Step-by-step

**1. Upload**

The user uploads a PDF file through the web UI. The frontend sends it to `POST /api/documents/upload` as a multipart form.

**2. Text Extraction**

The backend extracts raw text from the PDF using `pypdf.PdfReader`. Each page's text is concatenated into a single string.

```
PDF File  ──>  pypdf.PdfReader  ──>  Raw Text (all pages combined)
```

**3. Text Chunking**

The raw text is split into overlapping chunks using LangChain's `RecursiveCharacterTextSplitter`:

- **Chunk size**: 500 characters
- **Chunk overlap**: 50 characters
- **Separators**: `\n\n`, `\n`, ` `, `` (hierarchical splitting)

This ensures each chunk is small enough for effective embedding while maintaining context through overlap.

**4. Batch Embedding**

All chunks are sent to the OpenAI Embeddings API in a single batch request:

- **Model**: `text-embedding-3-small`
- **Dimensions**: 1536-dimensional float vectors
- **Batch processing**: All chunks embedded in one API call for efficiency

**5. Storage in Couchbase**

Each chunk is stored as a separate document in Couchbase with the following structure:

```json
{
  "text": "The chunk's text content...",
  "embedding": [0.0123, -0.0456, ...],   // 1536-dim vector
  "metadata": {
    "source_filename": "document.pdf",
    "chunk_index": 0
  }
}
```

- **Collection**: `documents` (in `_default` scope)
- **Document ID**: `{filename}::chunk_{index}`

**6. Vector Search Index**

A Couchbase Full-Text Search (FTS) index is automatically created with:

- **Vector field** (`embedding`): 1536 dimensions, `dot_product` similarity, optimized for recall
- **Text field** (`text`): Full-text indexed with `store: true` for result retrieval

**7. Vocabulary Extraction**

After storing chunks, the system extracts key technical terms using regex patterns:

- **Acronyms**: 2+ uppercase letters (e.g., `XDCR`, `N1QL`, `SDK`)
- **CamelCase words**: Mixed-case identifiers (e.g., `MapReduce`, `CouchbaseLite`)
- **Capitalized terms**: Proper nouns and technical terms

These vocabulary hints are stored in Couchbase and injected into the AI system prompt to improve speech recognition accuracy for domain-specific terminology.

## RAG Pipeline

When a user asks a question (via voice or text), the system performs Retrieval-Augmented Generation through the OpenAI Realtime API's function calling mechanism:

```
  User            Frontend          Backend         OpenAI Realtime    OpenAI Embeddings   Couchbase
   |                 |                 |                  |                   |                |
   | Voice/Text      |                 |                  |                   |                |
   +---------------->|  WebSocket      |                  |                   |                |
   |                 +---------------->|  Relay audio/text|                   |                |
   |                 |                 +----------------->|                   |                |
   |                 |                 |                  |                   |                |
   |                 |                 |    [Deepgram STT + LLM Analysis]     |                |
   |                 |                 |                  |                   |                |
   |                 |                 |  Function Call:  |                   |                |
   |                 |   searching     |  search_kb(query)|                   |                |
   |                 |<----------------+<-----------------+                   |                |
   |                 |                 |                                      |                |
   |                 |                 |  Generate query embedding            |                |
   |                 |                 +------------------------------------->|                |
   |                 |                 |                  1536-dim vector     |                |
   |                 |                 |<-------------------------------------+                |
   |                 |                 |                                                       |
   |                 |                 |  Vector search (dot_product, top 3)                   |
   |                 |                 +----------------------------------------------------->|
   |                 |                 |                                      Matching chunks  |
   |                 |                 |<-----------------------------------------------------+
   |                 |                 |                  |                   |                |
   |                 |                 |  Function output |                   |                |
   |                 |                 |  (context)       |                   |                |
   |                 |                 +----------------->|                   |                |
   |                 |                 |                  |                   |                |
   |                 |                 |    [Generate response grounded in context]            |
   |                 |                 |                  |                   |                |
   |                 |  audio.delta +  |  Audio+transcript|                   |                |
   |  Voice playback |  transcript     |  stream          |                   |                |
   |  + text display |<----------------+<-----------------+                   |                |
   |<----------------+                 |                  |                   |                |
```

### Step-by-step

**1. User Input**

The user speaks into the microphone or types a message. Audio is captured at 24kHz PCM16 format via an AudioWorklet processor and streamed through a WebSocket connection.

```
Microphone ──> AudioWorklet (24kHz PCM16) ──> WebSocket ──> Backend ──> OpenAI
```

For text input, the message is sent directly through the same WebSocket connection.

**2. OpenAI Realtime API Processing**

The backend maintains a WebSocket relay between the client and OpenAI's Realtime API. The AI model:

- Transcribes speech to text using Deepgram (required for voice mode)
- Analyzes the user's question
- Decides whether to call the `search_knowledge_base` tool

The tool is defined with the following schema:

```json
{
  "type": "function",
  "name": "search_knowledge_base",
  "description": "Search the knowledge base for information relevant to the user's question.",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "The search query based on what the user is asking about"
      }
    },
    "required": ["query"]
  }
}
```

**3. Vector Search (RAG Retrieval)**

When the tool is called, the backend:

1. Generates an embedding for the search query using OpenAI's Embeddings API
2. Performs a vector similarity search in Couchbase using `dot_product`
3. Returns the top 3 most relevant chunks

```python
embedding = embedding_service.get_embedding(query)        # 1536-dim vector
results = couchbase_service.vector_search(embedding, top_k=3)  # dot_product similarity
context = "\n\n---\n\n".join([r["text"] for r in results])
```

**4. Context-Augmented Response**

The retrieved chunks are sent back to the OpenAI Realtime API as the function call output. The AI then generates a response that:

- Is grounded in the retrieved document context
- Is delivered as both audio (voice) and text (transcript)
- Streams back to the client in real-time

**5. Client Playback**

The frontend receives audio deltas (base64-encoded PCM16) and transcript fragments via WebSocket, queues them for playback through the Web Audio API, and displays the transcript in the chat interface.

## Prerequisites

- **Node.js** 20+
- **Python** 3.13+
- **Docker** and **Docker Compose**
- **Azure OpenAI** with Realtime API and Embedding deployments
- **Couchbase** - either:
  - Local instance via Docker (included in `docker-compose.yml`)
  - [Couchbase Capella](https://cloud.couchbase.com/) (cloud-hosted)

## Getting Started

The Settings UI is the single bring-up path: on first login you'll see one form pre-filled from `.env` (or `docker-compose.yml`) covering Couchbase, Azure OpenAI, Capella API keys, Deepgram, Tavily, and a "Web search fallback" toggle. Secret inputs render their stored value as `type=password` (dot-masked) with an eye icon to toggle plaintext view, like any password manager. Confirm or edit, click **Connect & Initialize**, and the backend creates the DB user, bucket, scope, collection, and search-index for you. The backend never auto-connects from `.env` alone — you always go through the UI. Every secret on disk is Fernet-encrypted; the key is derived from `JWT_SECRET` via HKDF-SHA256, so rotating `JWT_SECRET` invalidates saved settings on purpose. The Tavily switch gates whether the LLM is even offered the `search_web` tool, so KB-only behaviour is honestly enforced when the operator turns web fallback off.

Pick one of two paths — the rest of the app behaves identically:

- **Quick start (Docker Compose)** — bundled Couchbase 8.0 container, zero manual cluster setup. Best for trying the demo or local development.
- **Production-style (Couchbase Capella)** — managed Capella cluster. Best for showing the real deployment shape.

### Quick start — Docker Compose

```bash
git clone <repository-url>
cd couchbase-realtime-rag
cp .env.example .env
# Edit .env (see "Minimum required" below)
docker-compose up
```

**Minimum required in `.env`:**

| Variable | Why |
|---|---|
| `AZURE_OPENAI_ENDPOINT` | Base resource URL for the Realtime LLM and embedding model. App will not start a chat session without it. |
| `OPENAI_API_KEY` | Azure OpenAI key matching the endpoint above. |
| `DEEPGRAM_API_KEY` | Required for **voice** mode. Without this key `/ws/deepgram` closes with code 4002 and the mic button is disabled (text chat still works). |

**Optional but recommended:**

| Variable | Why |
|---|---|
| `TAVILY_API_KEY` + `WEB_SEARCH_ENABLED=true` | Lets the LLM fall back to web search when the knowledge base has no relevant chunks. Without these the assistant says "I don't have that in the knowledge base" instead. |
| `JWT_SECRET` (32+ chars) | Stable session signing across restarts. Empty = random per-process secret (every restart logs everyone out). |
| `CAPELLA_API_KEY_ID` + `CAPELLA_API_KEY_TOKEN` | Only when you point at Couchbase Capella with `EMBEDDING_METHOD=capella` — see the Capella section below. |

> **`AZURE_OPENAI_ENDPOINT` is the base resource URL** (`https://<your-resource>.openai.azure.com`) — do not paste the full realtime URL with `/openai/realtime?api-version=...&deployment=...`. The backend builds that path itself; including it yields a double-path 400 on the voice WebSocket.

1. Open http://localhost:3000 and log in with `admin` / `admin`.
2. The Settings page shows up with `.env`-supplied defaults already filled in:
   - **Connection String**: `couchbase://couchbase-server` (the bundled service hostname)
   - **Username**: `Administrator`
   - **Password**: blank — type the cluster admin password you want
   - **Bucket**: `realtime-rag`
   - **Scope**: `_default`
   - **Embedding method**: `Python (local)`
   - **Collection** / **Search index**: derived from the embedding method
3. Click **Connect & Initialize**. The backend bootstraps the cluster, creates the bucket and indexes, and lands you on /chat.

Want the Settings UI to come up with values you supply (e.g. a different password)? Edit `.env` before `docker-compose up` — every value there reaches the backend container unchanged.

#### Stopping the dev stack

`docker-compose up` traps `Ctrl+C` (SIGINT) and shuts containers down gracefully — that is the normal way to bring the stack down. Avoid `Ctrl+Z` (SIGTSTP): it only suspends the docker-compose CLI itself, the containers keep running on the Docker daemon, and the next `docker-compose up` will complain about existing or orphaned containers.

If you did press `Ctrl+Z` by accident:

- Same terminal — `fg` to resume the suspended `docker-compose up`, then `Ctrl+C`.
- Another shell — `docker-compose stop` (graceful) or `docker-compose down` (graceful + remove containers).

#### What persists across restarts

The compose file mounts two host-side locations into the containers, so the following all survive `Ctrl+C` and even `docker-compose down`:

| What | Where on host | Notes |
|------|---------------|-------|
| Couchbase data (bucket, FTS index, users, cluster config) | named volume `couchbase-data` | Created and managed by Docker; inspect with `docker volume inspect couchbase-realtime-rag_couchbase-data`. |
| Backend saved settings (`db_settings.json`, `app_users.json`) | `./backend/data/` (bind mount) | `.gitignore`'d; secrets in `db_settings.json` are Fernet-encrypted with a key derived from `JWT_SECRET`. |

With a stable `JWT_SECRET` in `.env` (32+ chars), the recommended day-to-day cycle is just:

```bash
docker-compose up         # Ctrl+C when done
docker-compose up         # next session: Settings UI auto-fills, backend reconnects
```

After pulling new code or editing the backend, add `--build` so Docker rebuilds the backend image instead of reusing the cached one (`docker-compose up --build`). Otherwise the running container keeps serving the previous Python code even though the host repo has the new version.

No `down` between sessions is needed for ordinary work. `docker-compose down` is for releasing containers / networks (volumes still survive); use `docker-compose down -v --remove-orphans` only when you actually want to throw away the Couchbase data and re-do Save & Connect from a fresh cluster.

### Production-style — Couchbase Capella

In the Capella console, do **two things once**:

1. **Create a cluster** (any region/size).
2. **Create an organisation API key** with project read+write access.

That's all the manual setup — DB user and bucket are auto-created by the demo on Save & Connect.

Edit `.env`:

```
AZURE_OPENAI_ENDPOINT=...
OPENAI_API_KEY=...

# Required for voice mode; omit and the mic button stays disabled (text chat still works).
DEEPGRAM_API_KEY=...

# Optional KB-miss fallback (also flip the Settings UI toggle on Save & Connect).
# TAVILY_API_KEY=...
# WEB_SEARCH_ENABLED=true

CB_CONNECTION_STRING=couchbases://cb.<id>.cloud.couchbase.com
CB_USERNAME=<DB user the demo will create>
CB_PASSWORD=<that user's password>
CB_BUCKET=realtime-rag
EMBEDDING_METHOD=capella

CAPELLA_API_KEY_ID=...
CAPELLA_API_KEY_TOKEN=...
```

Start the demo with the Capella override file — it removes the dependency on the bundled couchbase container so `up frontend backend` doesn't transitively start it (the base compose file no longer carries `environment:` overrides, so this is the only thing the Capella override has to do):

```bash
docker-compose -f docker-compose.yml -f docker-compose.capella.yml \
  up frontend backend
```

Or set it once per shell:

```bash
export COMPOSE_FILE=docker-compose.yml:docker-compose.capella.yml
docker-compose up frontend backend
```

> Need backend hot-reload during development? Skip the override and run the backend manually instead: `cd backend && uv sync && source .venv/bin/activate && uvicorn main:app --port 8000 --reload`, with `docker-compose up frontend` for the UI.

Open http://localhost:3000, log in, confirm the pre-filled Capella values, click **Connect & Initialize**. The backend uses the Capella Management API to create the DB user and bucket, then SDK-creates collections + search index + AI Workflow.

> **Already-managed self-hosted Couchbase?** Pre-create a DB user with read+write access to a bucket, fill `.env` accordingly, run `docker-compose up frontend` + manual backend, and the same Settings UI flow applies.

### Manual Development (without Docker)

You'll need a Couchbase instance reachable from your host — point `CB_CONNECTION_STRING` at either a Capella cluster (see above) or any self-hosted Couchbase (just pre-create the bucket; the app handles collections + search index either way). For a manual backend run against a local Couchbase install, set `CB_CONNECTION_STRING=couchbase://localhost` in `.env` (the docker-compose default `couchbase://couchbase` is a service hostname that only resolves inside the compose network).

System dependencies (one-time):
- **macOS**: `brew install libmagic`
- **Debian / Ubuntu**: `sudo apt-get install libmagic1`
- **Alpine**: `apk add file`

The backend uses `python-magic` to MIME-detect uploaded files; the matching system library must be installed for the Python bindings to load.

The frontend uses [`pnpm`](https://pnpm.io/) (pinned via `packageManager` in `frontend/package.json`). Run `corepack enable` once to activate the bundled pnpm — Node 20+ ships with corepack.

Root-level npm scripts launch both services and handle venv / `pnpm install` on first run:

```bash
# In two separate terminals:
npm run dev:api   # FastAPI backend on :58000 (creates backend/.venv automatically)
npm run dev       # Next.js frontend on :53000 (uses pnpm under the hood)
```

Override ports by setting `PORT`:

```bash
PORT=8080 npm run dev:api
PORT=4000 npm run dev
```

Both scripts load the repo-root `.env` file if present. The frontend proxies `/api/*` and `/ws/*` to `http://localhost:58000` via Next.js rewrites.

If you prefer running them manually, the backend uses [`uv`](https://docs.astral.sh/uv/) for dependency management:

```bash
# Backend (recommended: uv)
cd backend
uv sync                                  # creates .venv and installs locked deps
source .venv/bin/activate
uvicorn main:app --reload --port 8000

# Backend (fallback: plain pip)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # requirements.txt is exported from uv.lock
uvicorn main:app --reload --port 8000

# Frontend (one-time: corepack enable)
cd frontend
pnpm install
pnpm run dev
```

**Install `uv`** (one-time, if missing): `brew install uv` (macOS) or `curl -LsSf https://astral.sh/uv/install.sh | sh` (other systems).

**Updating dependencies**:

```bash
cd backend
uv add <package>               # add a new dependency
uv lock --upgrade              # refresh uv.lock to the latest allowed versions
uv export --format requirements-txt --no-hashes --no-emit-project -o requirements.txt
```

`requirements.txt` is the frozen snapshot consumed by `Dockerfile.backend` and the `pip` fallback, and must be regenerated whenever `uv.lock` changes.

**Regenerating the typed API surface** (after touching any router / response model):

```bash
# backend (produces backend/openapi.json — committed)
cd backend && uv run python scripts/dump_openapi.py

# frontend (reads ../backend/openapi.json → src/types/api.d.ts — committed)
cd ../frontend && pnpm run generate-api
```

`backend/openapi.json` is the single source of truth that the frontend consumes via `openapi-typescript`. CI re-runs `scripts/dump_openapi.py` and refuses PRs whose committed `openapi.json` drifted from the live schema.

**Backend tests** run against the isolated in-memory fixtures in `backend/tests/`:

```bash
cd backend
uv run pytest -q            # 70 tests; Couchbase / Capella API / OpenAI / Tavily stubbed
uv run ruff check .         # lint
```

The same two commands run in CI on every push/PR via `.github/workflows/backend-tests.yml`, and a root `.pre-commit-config.yaml` wires them into `pre-commit` (`pytest` is bound to the `pre-push` stage so commits stay fast). The backend job also re-dumps `openapi.json` and fails on drift.

**Frontend tests** are split into hermetic unit tests (Vitest + React Testing Library + MSW) and a full-stack Playwright smoke (real FastAPI backend + Next dev server, Couchbase-dependent routes stubbed via `page.route()`):

```bash
cd frontend
pnpm run typecheck && pnpm run lint && pnpm run format:check
pnpm run test              # 28 unit/component tests
pnpm run e2e               # 3 Playwright tests incl. axe-core a11y scans on /login + /chat
```

`.github/workflows/frontend-tests.yml` runs both as separate jobs (`unit` and `e2e`); the e2e job uploads the `playwright-report/` artifact on failure.

> **Tip**: A Capella connection string starts with `couchbases://` (note the trailing `s`). When `CAPELLA_API_KEY_ID/TOKEN` are set, the app creates the bucket automatically via the Capella Management API; otherwise pre-create it in the Capella console. Collections and the vector search index are always created by the app.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_USERS` | Login credentials (`user:pass`, comma-separated for multiple) | `admin:admin` |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint URL (required) | - |
| `OPENAI_API_KEY` | Azure OpenAI API key (required) | - |
| `OPENAI_REALTIME_MODEL` | Azure OpenAI Realtime deployment name | `gpt-realtime` |
| `OPENAI_EMBEDDING_MODEL` | Azure OpenAI Embedding deployment name | `text-embedding-3-small` |
| `CB_CONNECTION_STRING` | Couchbase connection string | `couchbase://localhost` |
| `CB_USERNAME` | Couchbase username | `Administrator` |
| `CB_PASSWORD` | Couchbase password | `password` |
| `CB_BUCKET` | Couchbase bucket name | `realtime-rag` |
| `CB_SCOPE` | Couchbase scope | `_default` |
| `CB_COLLECTION` | Couchbase collection for documents (blank → derived from `EMBEDDING_METHOD`) | - |
| `CB_SEARCH_INDEX` | Couchbase FTS index name (blank → derived from `EMBEDDING_METHOD`) | - |
| `EMBEDDING_METHOD` | `python` (local Azure OpenAI embeddings) or `capella` (Capella AI Workflow) | `python` |
| `DEEPGRAM_API_KEY` | Deepgram API key — **required for voice STT** (without it `/ws/deepgram` closes 4002 and the mic button is disabled) | - |
| `TAVILY_API_KEY` | Tavily API key — enables KB-miss web-search fallback (also needs `WEB_SEARCH_ENABLED=true`) | - |
| `WEB_SEARCH_ENABLED` | Default state for the Settings UI's web-search toggle | `false` |
| `CAPELLA_API_KEY_ID` | Capella Management API key ID (only when `EMBEDDING_METHOD=capella`) | - |
| `CAPELLA_API_KEY_TOKEN` | Capella Management API key token (only when `EMBEDDING_METHOD=capella`) | - |
| `JWT_SECRET` | JWT signing secret (32+ chars required; a session-scoped random secret is generated when empty) | - |
| `LOG_LEVEL` | Root log level for JSON logging (`DEBUG`, `INFO`, `WARNING`, ...) | `INFO` |
| `GUNICORN_WORKERS` | Number of Gunicorn workers inside the container | `2` |
| `GUNICORN_TIMEOUT` | Gunicorn request timeout in seconds | `120` |
| `GUNICORN_KEEPALIVE` | Gunicorn keep-alive in seconds | `5` |

## Container runtime

`Dockerfile.backend` runs the API under Gunicorn with Uvicorn workers for multi-process concurrency and graceful reloads:

```
gunicorn main:app \
    --workers ${GUNICORN_WORKERS:-2} \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --timeout ${GUNICORN_TIMEOUT:-120} \
    --keep-alive ${GUNICORN_KEEPALIVE:-5}
```

Tune worker count via the `GUNICORN_WORKERS`, `GUNICORN_TIMEOUT`, and `GUNICORN_KEEPALIVE` environment variables when deploying.

## Observability

All application logs are emitted as one JSON object per line (`python-json-logger`) so log aggregators (Azure Log Analytics, Datadog, CloudWatch, etc.) can parse them without custom regexes. Each record includes:

```json
{
  "timestamp": "2026-04-23T07:27:12.396Z",
  "level": "INFO",
  "logger": "uvicorn.access",
  "message": "127.0.0.1:58697 - \"GET /api/health HTTP/1.1\" 200",
  "request_id": "ce543fc6d3864fc49c3975a7f5c16a7f"
}
```

A `RequestIDMiddleware` assigns each request a UUID (or honours an inbound `X-Request-ID` header), propagates it via `ContextVar` so every log line emitted during the request carries the same id, and echoes it back on the response as `X-Request-ID`. Override the root log level with `LOG_LEVEL=DEBUG` (or `WARNING`, etc.) at runtime.

## API Reference

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/auth/login` | Authenticate; backend issues an httpOnly `token` cookie (`Secure; SameSite=None`) |
| `POST` | `/api/auth/logout` | Clear authentication (client-side only) |
| `POST` | `/api/auth/force-logout` | Invalidate all active tokens server-side (all users logged out immediately) |
| `GET` | `/api/auth/me` | Get current user info |
| `GET` | `/api/documents` | List uploaded documents with chunk counts |
| `POST` | `/api/documents/upload` | Upload a PDF document |
| `DELETE` | `/api/documents/{filename}` | Delete a document and its chunks |
| `GET` | `/api/chat/sessions` | List chat sessions |
| `GET` | `/api/chat/sessions/{id}` | Load a chat session |
| `POST` | `/api/chat/sessions/{id}` | Save a chat session |
| `DELETE` | `/api/chat/sessions/{id}` | Delete a chat session |
| `GET` | `/api/settings/status` | Check if Couchbase is initialized |
| `GET` | `/api/settings` | Get current Couchbase settings |
| `POST` | `/api/settings` | Save and apply Couchbase settings |
| `GET` | `/api/health` | Health check |

### WebSocket Endpoint

| Path | Description |
|------|-------------|
| `WS /ws/realtime` | Real-time voice/text relay to OpenAI. Auth via httpOnly `token` cookie. Close `4003` when the `Origin` header is missing or not on `config.ALLOWED_ORIGINS`; close `4001` when the cookie is missing/expired. |
| `WS /ws/deepgram` | Deepgram STT for accurate transcription. Same cookie + Origin gate. |

**Client-to-Server messages:**

| Type | Description |
|------|-------------|
| `audio.append` | Send audio chunk (base64 PCM16) |
| `audio.commit` | Signal end of speech |
| `text.send` | Send text message |
| `session.config` | Update session settings (voice, instructions) |

**Server-to-Client messages:**

| Type | Description |
|------|-------------|
| `audio.delta` | Audio response chunk (base64 PCM16) |
| `audio.done` | Audio response complete |
| `transcript.partial` | Partial assistant transcript |
| `transcript.done` | Complete transcript (user or assistant) |
| `text.delta` | Text response chunk |
| `text.done` | Text response complete |
| `function_call.searching` | Knowledge base search in progress |
| `function_call.results` | Search results count |
| `error` | Error message |

## Project Structure

```
couchbase-realtime-rag/
+-- backend/
|   +-- main.py                     # FastAPI app, lifespan, CORS (reads config.ALLOWED_ORIGINS), router registration
|   +-- config.py                   # pydantic-settings typed config + ALLOWED_ORIGINS shared with WS gate
|   +-- logging_config.py           # JSON logging + request_id filter
|   +-- openapi.json                # Committed schema dump — frontend api.d.ts source of truth
|   +-- pyproject.toml              # Project metadata + runtime dependencies (uv)
|   +-- uv.lock                     # Resolved dependency lockfile (committed)
|   +-- requirements.txt            # Frozen snapshot exported from uv.lock (pip fallback)
|   +-- scripts/
|   |   +-- dump_openapi.py         # CI re-runs this and fails if openapi.json drifted
|   |   +-- seed_e2e_user.py        # Playwright fixture helper
|   +-- middleware/
|   |   +-- auth.py                 # JWT creation, verification, token_version lock
|   |   +-- rate_limit.py           # slowapi Limiter singleton
|   |   +-- request_id.py           # ASGI middleware + ContextVar for request ids
|   +-- models/                     # Shared Pydantic request/response models (OpenAPI)
|   |   +-- auth.py, chat.py, documents.py, settings.py, common.py
|   +-- routers/
|   |   +-- auth.py                 # Login (sets httpOnly cookie), logout, change-password, force-logout, /me
|   |   +-- chat.py                 # Chat session CRUD
|   |   +-- documents.py            # Document upload (EXT_TO_MIME) / list / status / delete
|   |   +-- realtime.py             # /ws/realtime + /ws/deepgram, Origin allowlist + cookie auth
|   |   +-- settings.py             # Couchbase connection settings (SecretStr-masked password)
|   +-- services/
|   |   +-- capella_ai_service.py    # Capella AI Workflows Management API client (async)
|   |   +-- couchbase_service.py    # Couchbase connection, vector search, CRUD
|   |   +-- document_service.py     # PDF parsing, chunking, embedding, vocab extraction
|   |   +-- embedding_service.py    # OpenAI embedding generation
|   |   +-- realtime_service.py     # OpenAI Realtime API WebSocket relay + RAG
|   |   +-- settings_store.py       # Local JSON file settings persistence
|   |   +-- user_store.py           # bcrypt-hashed app user persistence
|   |   +-- web_search_service.py   # Tavily web-search fallback
|   +-- utils/
|   |   +-- filenames.py            # safe_filename sanitizer
|   |   +-- text_splitter.py        # Text chunking with LangChain
|   +-- data/                       # Bind-mounted from host (.gitignore'd); db_settings.json + app_users.json persist across restarts
+-- docs/
|   +-- CAPELLA_AI_SERVICES_SETUP.md      # Capella AI Workflows setup walkthrough
|   +-- FEATURE_FLOWS.md                  # End-to-end feature sequence diagrams
|   +-- SDK_4_6_0_VECTOR_SEARCH_BUG.md    # Upstream-ready report for the SDK routing gap that vector_search works around
+-- frontend/
|   +-- vitest.config.ts            # jsdom + alias @ → src
|   +-- playwright.config.ts        # webServer array boots real backend (58001) + Next dev (53001)
|   +-- src/
|   |   +-- app/
|   |   |   +-- layout.tsx                  # ErrorBoundary + sonner Toaster wrap
|   |   |   +-- page.tsx                    # Home page (redirect)
|   |   |   +-- chat/page.tsx               # Main chat page with session management
|   |   |   +-- login/page.tsx              # Login page
|   |   |   +-- change-password/page.tsx    # Forced + voluntary password change
|   |   |   +-- settings/cluster/page.tsx   # Couchbase settings entry
|   |   +-- components/
|   |   |   +-- ChatInterface.tsx   # Message display, text input, voice button
|   |   |   +-- ChatHistory.tsx     # Session list in sidebar
|   |   |   +-- ErrorBoundary.tsx   # Class boundary with Reload + Copy details
|   |   |   +-- FileUpload.tsx      # PDF upload with drag-and-drop
|   |   |   +-- LoginForm.tsx       # Authentication form
|   |   |   +-- SettingsForm.tsx    # Couchbase connection settings UI (password Edit lock)
|   |   |   +-- Sidebar.tsx         # Navigation sidebar with logo (next/image)
|   |   |   +-- VoiceButton.tsx     # Microphone button with status indicators
|   |   +-- hooks/
|   |   |   +-- useAuth.ts          # Cookie-driven session state (no localStorage)
|   |   |   +-- useRealtimeAudio.ts # WebSocket relay; cookie auto-attached
|   |   +-- lib/
|   |   |   +-- api.ts              # fetch wrapper that throws ApiError(status, detail, requestId)
|   |   |   +-- errors.ts           # toastApiError per-status mapping
|   |   |   +-- constants.ts        # API_BASE, WS_BASE URLs
|   |   +-- types/
|   |   |   +-- api.d.ts            # Generated by openapi-typescript from backend/openapi.json
|   |   |   +-- index.ts            # UI types + re-exports of generated API schemas
|   |   +-- test/                   # Vitest setup + MSW server + sonner mock helper
|   +-- e2e/
|   |   +-- smoke.spec.ts           # Playwright: axe a11y on /login + /chat, login→chat→logout
|   +-- public/
|   |   +-- couchbase-logo.png
|   +-- next.config.ts              # Standalone output, API rewrites
|   +-- package.json
|   +-- tsconfig.json
+-- Dockerfile.backend
+-- Dockerfile.frontend
+-- docker-compose.yml
+-- scripts/
|   +-- dev-backend.sh              # Local FastAPI dev server
|   +-- dev-frontend.sh             # Local Next.js dev server
+-- .env.example
```
