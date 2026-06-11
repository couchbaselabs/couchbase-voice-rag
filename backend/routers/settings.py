import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

import config
from middleware.auth import get_current_user
from models.settings import (
    SaveSettingsResponse,
    SettingsProgressResponse,
    SettingsRequest,
    SettingsResponse,
    SettingsStatusResponse,
    SettingsValues,
)
from services import capella_management_service, couchbase_service, settings_store

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_defaults() -> dict:
    """Return current env-driven defaults that the Settings UI pre-fills with."""
    return {
        "cb_connection_string": config.settings.cb_connection_string,
        "cb_username": config.settings.cb_username,
        "cb_password": config.settings.cb_password,
        "cb_bucket": config.settings.cb_bucket,
        "cb_scope": config.settings.cb_scope or "_default",
        "cb_collection": config.settings.cb_collection,
        "cb_search_index": config.settings.cb_search_index,
        "embedding_method": config.settings.embedding_method_default,
        "azure_openai_endpoint": config.settings.azure_openai_endpoint,
        "openai_api_key": config.settings.openai_api_key,
        "openai_realtime_model": config.settings.openai_realtime_model,
        "openai_embedding_model": config.settings.openai_embedding_model,
        "capella_api_key_id": config.settings.capella_api_key_id,
        "capella_api_key_token": config.settings.capella_api_key_token,
        "capella_workflow_name": config.settings.capella_workflow_name,
        "deepgram_api_key": config.settings.deepgram_api_key,
        "tavily_api_key": config.settings.tavily_api_key,
        "web_search_enabled": config.settings.web_search_enabled,
    }


def _set_progress(stage: str) -> None:
    """Record the current Save & Connect stage on app.state for /progress polling."""
    from main import app

    app.state.settings_progress = {"stage": stage}


def _apply_settings(values: dict):
    """Mirror the UI-submitted settings onto the live Settings instance verbatim."""
    config.settings.cb_connection_string = values["cb_connection_string"]
    config.settings.cb_username = values["cb_username"]
    config.settings.cb_password = values["cb_password"]
    config.settings.cb_bucket = values["cb_bucket"]
    config.settings.cb_scope = values["cb_scope"]
    config.settings.cb_collection = values["cb_collection"]
    config.settings.cb_search_index = values["cb_search_index"]
    config.settings.azure_openai_endpoint = values["azure_openai_endpoint"]
    config.settings.openai_api_key = values["openai_api_key"]
    config.settings.openai_realtime_model = values["openai_realtime_model"]
    config.settings.openai_embedding_model = values["openai_embedding_model"]
    config.settings.capella_api_key_id = values["capella_api_key_id"]
    config.settings.capella_api_key_token = values["capella_api_key_token"]
    # Blank from the UI falls back to the in-code default so the
    # Capella AI workflow lookup always has a name to match against.
    config.settings.capella_workflow_name = (
        values["capella_workflow_name"] or "realtime_rag_vectorization"
    )
    config.settings.deepgram_api_key = values["deepgram_api_key"]
    config.settings.tavily_api_key = values["tavily_api_key"]
    config.settings.web_search_enabled = bool(values["web_search_enabled"])


@router.get(
    "/status",
    response_model=SettingsStatusResponse,
    summary="Check Couchbase connection status",
)
async def settings_status(_: str = Depends(get_current_user)):
    """Return whether the server currently holds a live Couchbase connection.

    Falls back to the on-disk settings file if this worker's in-memory
    ``cb_initialized`` flag is False. Multi-worker deployments only run
    lifespan-init once per process, so a request can land on a worker that
    missed the original Save & Connect even though the cluster is fully
    set up. In that case we lazily apply the saved settings + reconnect on
    the worker, mirroring what lifespan would have done.
    """
    from main import _apply_saved_settings, _try_init_couchbase, app

    if getattr(app.state, "cb_initialized", False):
        return SettingsStatusResponse(initialized=True)

    saved = settings_store.load_settings()
    if not saved:
        return SettingsStatusResponse(initialized=False)

    _apply_saved_settings(saved)
    method = saved.get("embedding_method", "")
    if await _try_init_couchbase(method):
        app.state.cb_initialized = True
        return SettingsStatusResponse(initialized=True)

    return SettingsStatusResponse(initialized=False)


@router.get(
    "/progress",
    response_model=SettingsProgressResponse,
    summary="Current Save & Connect progress stage",
)
def settings_progress(_: str = Depends(get_current_user)):
    """Return the stage of the most recent (or in-flight) Save & Connect.

    Polled by the Settings UI on ~0.5s intervals while the form is
    submitting so the button label can advance through "applying",
    "connecting", "creating_collections", "building_search_index", etc.
    The POST /api/settings call itself only resolves at the end of the
    multi-step setup, so without this endpoint the user has no
    indication of which step is currently running.
    """
    from main import app

    progress = getattr(app.state, "settings_progress", None) or {"stage": "idle"}
    return SettingsProgressResponse(stage=progress.get("stage", "idle"))


@router.get(
    "",
    response_model=SettingsResponse,
    summary="Read stored Couchbase settings",
)
def get_settings(_: str = Depends(get_current_user)):
    """Return stored settings, including secret fields.

    Authenticated callers get the same view they'd see in any password
    manager: the secret values are echoed so the UI can pre-fill inputs
    that render as ``type=password`` (dot-masked), with an eye toggle
    revealing plaintext on demand. The on-disk store stays
    Fernet-encrypted regardless.
    """
    saved = settings_store.load_settings()
    defaults = _get_defaults()
    values = {**defaults, **(saved or {})}
    return SettingsResponse(settings=SettingsValues(**values))


@router.post(
    "",
    response_model=SaveSettingsResponse,
    summary="Save Couchbase settings and reconnect",
)
async def save_settings(req: SettingsRequest, _: str = Depends(get_current_user)):
    """Persist new connection settings, reconnect to Couchbase, and re-run index setup.

    In Capella mode (and only when a Capella API key is configured), the
    DB user and bucket are auto-created via the Management API before the
    SDK connect attempt. The Docker scenario relies on
    ``couchbase_service._init_docker_cluster`` to bootstrap services /
    quotas / admin — that's invoked from inside ``connect()``.
    """
    from main import app

    settings = req.model_dump()
    # Unwrap SecretStr fields verbatim — GET echoes the stored values into
    # the UI, so the request body always carries the user's current intent
    # (whether unchanged, edited, or explicitly blanked).
    for key in settings_store.SECRET_KEYS:
        settings[key] = getattr(req, key).get_secret_value()

    if settings.get("embedding_method") not in ("python", "capella"):
        _set_progress("error")
        raise HTTPException(
            status_code=400,
            detail="embedding_method must be 'python' or 'capella'",
        )

    _set_progress("applying")
    _apply_settings(settings)
    couchbase_service.disconnect()

    method = settings["embedding_method"]
    try:
        if method == "capella" and capella_management_service.is_configured():
            # Capella user creation references the target bucket in its
            # access policy (resources.buckets[].name), and the Management
            # API rejects a user POST with 400 if that bucket does not
            # exist on the cluster yet. So bucket must come first, then
            # user. Both calls are idempotent on already-exists (409/422),
            # which keeps reruns on a pre-provisioned cluster safe.
            _set_progress("capella_bucket")
            await capella_management_service.ensure_bucket(
                name=settings["cb_bucket"],
                ram_quota_mb=256,
            )
            _set_progress("capella_user")
            await capella_management_service.ensure_user(
                username=settings["cb_username"],
                password=settings["cb_password"],
                bucket=settings["cb_bucket"],
            )
        _set_progress("connecting")
        await asyncio.to_thread(couchbase_service.connect)
        await asyncio.to_thread(couchbase_service.setup, _set_progress)
    except Exception as e:
        _set_progress("error")
        app.state.cb_initialized = False
        raise HTTPException(status_code=400, detail=f"Connection failed: {e}")

    _set_progress("saving")
    settings_store.save_settings(settings)
    app.state.cb_initialized = True
    _set_progress("done")

    return SaveSettingsResponse(message="Connected and initialized successfully")
