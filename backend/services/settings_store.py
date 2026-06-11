import json
import logging
import os

from cryptography.fernet import InvalidToken

from services import secrets_crypto

logger = logging.getLogger(__name__)

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "db_settings.json")

SETTING_KEYS = [
    "cb_connection_string",
    "cb_username",
    "cb_password",
    "cb_bucket",
    "cb_scope",
    "cb_collection",
    "cb_search_index",
    "embedding_method",
    "azure_openai_endpoint",
    "openai_api_key",
    "openai_realtime_model",
    "openai_embedding_model",
    "capella_api_key_id",
    "capella_api_key_token",
    "capella_workflow_name",
    "deepgram_api_key",
    "tavily_api_key",
    "web_search_enabled",
]

# Fields that contain operator secrets and must be encrypted on disk.
# `web_search_enabled` is a boolean toggle, not a secret.
SECRET_KEYS = (
    "cb_password",
    "openai_api_key",
    "capella_api_key_id",
    "capella_api_key_token",
    "deepgram_api_key",
    "tavily_api_key",
)


def _encrypt_secrets(settings: dict) -> dict:
    out = dict(settings)
    for key in SECRET_KEYS:
        value = out.get(key, "")
        if value:
            out[key] = secrets_crypto.encrypt(value)
    return out


def _decrypt_secrets(settings: dict) -> dict:
    out = dict(settings)
    for key in SECRET_KEYS:
        value = out.get(key, "")
        if not value:
            continue
        try:
            out[key] = secrets_crypto.decrypt(value)
        except InvalidToken:
            logger.warning(
                "Saved settings field %r could not be decrypted "
                "(JWT_SECRET likely rotated) — dropping it.",
                key,
            )
            out[key] = ""
    return out


def save_settings(settings: dict):
    """Persist the Couchbase settings dict to ``data/db_settings.json``.

    Secret fields (``cb_password``, ``openai_api_key``) are Fernet-encrypted
    in place before serialization; everything else is stored verbatim.
    """
    payload = _encrypt_secrets(settings)
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(payload, f)


def load_settings() -> dict | None:
    """Return previously saved Couchbase settings, or ``None`` when missing/invalid.

    Secret fields are decrypted on the way out. Legacy plaintext values
    (saved before this module existed) pass through unchanged thanks to
    the prefix check in ``secrets_crypto.decrypt``.
    """
    try:
        with open(SETTINGS_FILE) as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return _decrypt_secrets(raw)
