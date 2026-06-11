from logging_config import configure_logging

configure_logging()

import asyncio  # noqa: E402
import logging  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from slowapi.middleware import SlowAPIMiddleware  # noqa: E402

import config  # noqa: E402
from middleware.rate_limit import limiter  # noqa: E402
from middleware.request_id import RequestIDMiddleware  # noqa: E402
from services import (  # noqa: E402
    capella_management_service,
    couchbase_service,
    settings_store,
    user_store,
)

logger = logging.getLogger(__name__)


async def _ensure_capella_bucket_if_needed(method: str) -> None:
    """Auto-create the Capella bucket when running in Capella mode with API keys set."""
    if method != "capella":
        return
    if not capella_management_service.is_configured():
        return
    await capella_management_service.ensure_bucket(
        name=config.settings.cb_bucket,
        ram_quota_mb=256,
    )


async def _try_init_couchbase(method: str) -> bool:
    """Connect and initialize Couchbase. Returns True on success."""
    try:
        await _ensure_capella_bucket_if_needed(method)
        await asyncio.to_thread(couchbase_service.connect)
        await asyncio.to_thread(couchbase_service.setup)
        logger.info("Couchbase initialized successfully")
        return True
    except Exception as e:
        logger.warning("Couchbase initialization failed: %s", e)
        couchbase_service.disconnect()
        return False


def _apply_saved_settings(saved: dict):
    """Apply saved settings (cluster + OpenAI) to the active Settings instance.

    The Settings UI captures every field on Save, so this function copies
    them verbatim with no method-driven derivation. ``.get`` with a blank
    fallback keeps older saved files (which may predate the OpenAI block
    or the cb_collection/cb_search_index fields) from raising ``KeyError``.
    OpenAI fields without a saved value fall back to whatever ``Settings``
    holds (env defaults).
    """
    config.settings.cb_connection_string = saved["cb_connection_string"]
    config.settings.cb_username = saved["cb_username"]
    config.settings.cb_password = saved["cb_password"]
    config.settings.cb_bucket = saved["cb_bucket"]
    config.settings.cb_scope = saved.get("cb_scope", "_default")
    config.settings.cb_collection = saved.get("cb_collection", "")
    config.settings.cb_search_index = saved.get("cb_search_index", "")
    if saved.get("azure_openai_endpoint"):
        config.settings.azure_openai_endpoint = saved["azure_openai_endpoint"]
    if saved.get("openai_api_key"):
        config.settings.openai_api_key = saved["openai_api_key"]
    if saved.get("openai_realtime_model"):
        config.settings.openai_realtime_model = saved["openai_realtime_model"]
    if saved.get("openai_embedding_model"):
        config.settings.openai_embedding_model = saved["openai_embedding_model"]
    if saved.get("capella_api_key_id"):
        config.settings.capella_api_key_id = saved["capella_api_key_id"]
    if saved.get("capella_api_key_token"):
        config.settings.capella_api_key_token = saved["capella_api_key_token"]
    if saved.get("capella_workflow_name"):
        config.settings.capella_workflow_name = saved["capella_workflow_name"]
    if saved.get("deepgram_api_key"):
        config.settings.deepgram_api_key = saved["deepgram_api_key"]
    if saved.get("tavily_api_key"):
        config.settings.tavily_api_key = saved["tavily_api_key"]
    if "web_search_enabled" in saved:
        config.settings.web_search_enabled = bool(saved["web_search_enabled"])


def _seed_users_if_empty():
    seeded = user_store.seed_from_plain(config.settings.parse_users())
    if seeded:
        logger.info(
            "Seeded %d user(s) from APP_USERS env var into app_users.json",
            seeded,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _seed_users_if_empty()
    # Stage tracker for the Settings UI's Save & Connect button. Updated
    # in routers/settings.save_settings as the multi-step setup runs;
    # polled from the frontend via GET /api/settings/progress.
    app.state.settings_progress = {"stage": "idle"}

    # Cluster bring-up is owned by the Settings UI: env-only auto-connect
    # paths have been removed. We only retry against settings that were
    # successfully saved in a previous Settings UI Save & Connect.
    saved = settings_store.load_settings()
    if saved:
        logger.info("Found saved settings, trying to connect...")
        _apply_saved_settings(saved)
        method = saved.get("embedding_method", "")
        if await _try_init_couchbase(method):
            app.state.cb_initialized = True
            yield
            couchbase_service.disconnect()
            return

    logger.info("No saved settings — Settings UI will collect cluster info.")
    app.state.cb_initialized = False
    yield
    couchbase_service.disconnect()


API_DESCRIPTION = """\
Reference backend for the Couchbase Realtime Voice RAG demo.

The API exposes authentication, document ingestion, chat-history persistence,
Couchbase connection settings, and the WebSocket relay that bridges browser
audio to the Azure OpenAI Realtime API. Document uploads are chunked and
either embedded locally via ``text-embedding-3-small`` or vectorized through
the Capella AI Services workflow before being indexed for vector search.
"""

TAGS_METADATA = [
    {"name": "auth", "description": "Login, logout, password rotation, JWT invalidation."},
    {"name": "documents", "description": "Upload, list, and delete knowledge-base documents."},
    {"name": "chat", "description": "Persist and reload chat sessions."},
    {"name": "settings", "description": "Manage the Couchbase connection used by the backend."},
    {"name": "realtime", "description": "WebSocket relays for OpenAI Realtime and Deepgram STT."},
    {"name": "health", "description": "Liveness probe."},
]

app = FastAPI(
    title="Couchbase Realtime Voice RAG",
    description=API_DESCRIPTION,
    version="1.0.0",
    contact={"name": "Couchbase Realtime Voice RAG", "url": "https://github.com/"},
    license_info={"name": "Apache-2.0", "url": "https://www.apache.org/licenses/LICENSE-2.0"},
    openapi_tags=TAGS_METADATA,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestIDMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(config.ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from routers import auth, chat, documents, realtime, settings  # noqa: E402

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(realtime.router, tags=["realtime"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])


@app.get("/api/health", tags=["health"], summary="Liveness probe")
async def health_check():
    """Return ``{\"status\": \"ok\"}`` so load balancers can confirm the process is up."""
    return {"status": "ok"}
