"""Application settings loaded from environment variables and .env file.

All runtime-mutable fields live on the `settings` instance. Module-level
UPPERCASE accessors (e.g. `config.CB_COLLECTION`) are kept as read-only
proxies for backward compatibility with existing imports. Mutations must
go through `config.settings` directly.
"""

import logging
import secrets

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_MIN_JWT_SECRET_LENGTH = 32

# Origins allowed to call the HTTP API and open WebSocket handshakes.
# ``main.py`` feeds this to ``CORSMiddleware`` for HTTP, and
# ``routers/realtime.py`` mirrors it for WebSocket Origin validation
# (Starlette's CORSMiddleware does not gate WS handshakes).
ALLOWED_ORIGINS: tuple[str, ...] = (
    "http://localhost:3000",
    "http://localhost:53000",
    "http://localhost:53001",  # frontend/playwright.config.ts E2E port
    "https://couchbase-rag.ecoplanty.com",
    "https://couchbase-rag-frontend.delightfulwave-e5c7f6e3.eastus2.azurecontainerapps.io",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App authentication
    app_users: str = "admin:admin"
    jwt_secret: str = ""  # empty → generate session-scoped random secret

    # Azure OpenAI
    azure_openai_endpoint: str = ""
    openai_api_key: str = ""
    openai_realtime_model: str = "gpt-4o-mini-realtime-preview"
    openai_embedding_model: str = "text-embedding-3-small"

    # Couchbase connection — these surface as Settings UI defaults on
    # first login. Backend never auto-connects with them; Save & Connect
    # is the bring-up moment.
    cb_connection_string: str = ""
    cb_username: str = ""
    cb_password: str = ""
    cb_bucket: str = "realtime-rag"
    cb_scope: str = "_default"
    # collection / search-index default to blank; the Settings UI fills
    # them from EMBEDDING_METHOD (documents_local for python,
    # documents_capella for capella) and the user can override.
    cb_collection: str = ""
    cb_search_index: str = ""

    # Deepgram (STT) / Tavily (web search)
    deepgram_api_key: str = ""
    tavily_api_key: str = ""
    # Tavily web search fallback toggle. Off by default; enabling without
    # tavily_api_key is a no-op (the LLM tool list also requires the key).
    web_search_enabled: bool = Field(False, alias="WEB_SEARCH_ENABLED")

    # Capella AI Services (auto-enabled when ID and token are set)
    capella_api_key_id: str = ""
    capella_api_key_token: str = ""
    capella_org_id: str = ""
    capella_project_id: str = ""
    capella_cluster_id: str = ""
    capella_workflow_id: str = ""
    capella_workflow_name: str = "realtime_rag_vectorization"
    capella_ai_provider_id: str = ""

    # Embedding method default (env var: EMBEDDING_METHOD)
    embedding_method_default: str = Field("capella", alias="EMBEDDING_METHOD")

    # Fixed constants
    embedding_dimension: int = 1536
    chunk_size: int = 500
    chunk_overlap: int = 50

    @field_validator("jwt_secret", mode="after")
    @classmethod
    def _ensure_jwt_secret(cls, v: str) -> str:
        if v:
            if len(v) < _MIN_JWT_SECRET_LENGTH:
                raise ValueError(
                    "JWT_SECRET must be at least "
                    f"{_MIN_JWT_SECRET_LENGTH} characters"
                )
            return v
        # No secret configured: generate one for this process lifetime.
        # Tokens will be invalidated on restart; this is a safe default
        # for local dev and obvious for production to notice.
        generated = secrets.token_urlsafe(_MIN_JWT_SECRET_LENGTH)
        logger.warning(
            "JWT_SECRET not set; using session-scoped random secret. "
            "All tokens will be invalidated on restart."
        )
        return generated

    @property
    def capella_ai_enabled(self) -> bool:
        return bool(self.capella_api_key_id and self.capella_api_key_token)

    def parse_users(self) -> dict[str, str]:
        users: dict[str, str] = {}
        for pair in self.app_users.split(","):
            pair = pair.strip()
            if ":" in pair:
                username, password = pair.split(":", 1)
                users[username.strip()] = password.strip()
        return users

    def get_jwt_secret(self) -> str:
        return self.jwt_secret


settings = Settings()


# --- Backward-compat UPPERCASE module-level read proxies -----------------
# Existing modules read via `config.CB_FOO`. Writes must target
# `config.settings.cb_foo` directly — module-level assignment would shadow
# the proxy and silently break mutations.

_ATTR_MAP: dict[str, str] = {
    "APP_USERS": "app_users",
    "JWT_SECRET": "jwt_secret",
    "AZURE_OPENAI_ENDPOINT": "azure_openai_endpoint",
    "OPENAI_API_KEY": "openai_api_key",
    "OPENAI_REALTIME_MODEL": "openai_realtime_model",
    "OPENAI_EMBEDDING_MODEL": "openai_embedding_model",
    "CB_CONNECTION_STRING": "cb_connection_string",
    "CB_USERNAME": "cb_username",
    "CB_PASSWORD": "cb_password",
    "CB_BUCKET": "cb_bucket",
    "CB_SCOPE": "cb_scope",
    "CB_COLLECTION": "cb_collection",
    "CB_SEARCH_INDEX": "cb_search_index",
    "DEEPGRAM_API_KEY": "deepgram_api_key",
    "TAVILY_API_KEY": "tavily_api_key",
    "WEB_SEARCH_ENABLED": "web_search_enabled",
    "CAPELLA_API_KEY_ID": "capella_api_key_id",
    "CAPELLA_API_KEY_TOKEN": "capella_api_key_token",
    "CAPELLA_ORG_ID": "capella_org_id",
    "CAPELLA_PROJECT_ID": "capella_project_id",
    "CAPELLA_CLUSTER_ID": "capella_cluster_id",
    "CAPELLA_WORKFLOW_ID": "capella_workflow_id",
    "CAPELLA_WORKFLOW_NAME": "capella_workflow_name",
    "CAPELLA_AI_PROVIDER_ID": "capella_ai_provider_id",
    "CAPELLA_AI_ENABLED": "capella_ai_enabled",
    "EMBEDDING_METHOD_DEFAULT": "embedding_method_default",
    "EMBEDDING_DIMENSION": "embedding_dimension",
    "CHUNK_SIZE": "chunk_size",
    "CHUNK_OVERLAP": "chunk_overlap",
}


def __getattr__(name: str):
    attr = _ATTR_MAP.get(name)
    if attr is not None:
        return getattr(settings, attr)
    raise AttributeError(f"module 'config' has no attribute {name!r}")


def parse_users() -> dict[str, str]:
    return settings.parse_users()


def get_jwt_secret() -> str:
    return settings.get_jwt_secret()
