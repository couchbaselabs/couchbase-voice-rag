"""Tests for the Settings UI endpoints.

The Settings UI is the single bring-up path for cluster credentials,
so these tests cover the round-trip of all required fields plus the
auto-create branches (Capella DB user + bucket) that fire on Save.
"""


def _full_payload(**overrides):
    """Return a complete SettingsRequest payload with sensible defaults."""
    base = {
        "cb_connection_string": "couchbase://localhost",
        "cb_username": "admin",
        "cb_password": "pw",
        "cb_bucket": "rag",
        "cb_scope": "_default",
        "cb_collection": "documents_local",
        "cb_search_index": "vector-search-index-local",
        "embedding_method": "python",
        "azure_openai_endpoint": "https://example.openai.azure.com",
        "openai_api_key": "openai-key",
        "openai_realtime_model": "gpt-4o-mini-realtime-preview",
        "openai_embedding_model": "text-embedding-3-small",
        "capella_api_key_id": "",
        "capella_api_key_token": "",
        "capella_workflow_name": "realtime_rag_vectorization",
        "deepgram_api_key": "",
        "tavily_api_key": "",
        "web_search_enabled": False,
    }
    base.update(overrides)
    return base


def test_status_requires_auth(client):
    resp = client.get("/api/settings/status")
    assert resp.status_code == 401


def test_status_returns_initialized_flag(client, auth_headers):
    resp = client.get("/api/settings/status", headers=auth_headers)
    assert resp.status_code == 200
    assert "initialized" in resp.json()


def test_progress_requires_auth(client):
    resp = client.get("/api/settings/progress")
    assert resp.status_code == 401


def test_progress_returns_idle_initially(client, auth_headers):
    resp = client.get("/api/settings/progress", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"stage": "idle"}


def test_get_settings_echoes_secrets(client, auth_headers):
    """Secret fields round-trip through GET so the UI can pre-fill them."""
    from services import settings_store

    settings_store.save_settings(
        {
            "cb_connection_string": "couchbases://cb.example",
            "cb_username": "admin",
            "cb_password": "supersecret",
            "cb_bucket": "rag",
            "cb_scope": "_default",
            "cb_collection": "documents_capella",
            "cb_search_index": "vector-search-index-capella",
            "embedding_method": "capella",
            "azure_openai_endpoint": "https://example.openai.azure.com",
            "openai_api_key": "topsecretapikey",
            "openai_realtime_model": "gpt-realtime",
            "openai_embedding_model": "text-embedding-3-small",
            "capella_api_key_id": "k-id",
            "capella_api_key_token": "k-tok",
            "deepgram_api_key": "dg-key",
            "tavily_api_key": "tv-key",
            "web_search_enabled": True,
        }
    )

    resp = client.get("/api/settings", headers=auth_headers)
    assert resp.status_code == 200
    values = resp.json()["settings"]

    # Non-secret values round-trip
    assert values["cb_username"] == "admin"
    assert values["cb_collection"] == "documents_capella"
    assert values["cb_search_index"] == "vector-search-index-capella"
    assert values["azure_openai_endpoint"] == "https://example.openai.azure.com"
    assert values["openai_realtime_model"] == "gpt-realtime"
    assert values["web_search_enabled"] is True

    # Secret fields are echoed (UI masks them via type=password + eye toggle)
    assert values["cb_password"] == "supersecret"
    assert values["openai_api_key"] == "topsecretapikey"
    assert values["capella_api_key_id"] == "k-id"
    assert values["capella_api_key_token"] == "k-tok"
    assert values["deepgram_api_key"] == "dg-key"
    assert values["tavily_api_key"] == "tv-key"


def test_save_settings_round_trip(client, auth_headers):
    resp = client.post(
        "/api/settings",
        headers=auth_headers,
        json=_full_payload(),
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    from services import settings_store

    saved = settings_store.load_settings()
    assert saved["cb_connection_string"] == "couchbase://localhost"
    assert saved["embedding_method"] == "python"
    assert saved["cb_collection"] == "documents_local"
    assert saved["cb_search_index"] == "vector-search-index-local"


def test_save_settings_persists_secret_inputs_verbatim(client, auth_headers):
    """The UI sends current input values; backend stores them as-is."""
    from services import settings_store

    settings_store.save_settings(
        {
            "cb_connection_string": "couchbase://localhost",
            "cb_username": "admin",
            "cb_password": "old-password",
            "cb_bucket": "rag",
            "cb_scope": "_default",
            "cb_collection": "documents_local",
            "cb_search_index": "vector-search-index-local",
            "embedding_method": "python",
            "azure_openai_endpoint": "https://example.openai.azure.com",
            "openai_api_key": "old-openai",
            "openai_realtime_model": "gpt-realtime",
            "openai_embedding_model": "text-embedding-3-small",
            "capella_api_key_id": "old-cap-id",
            "capella_api_key_token": "old-cap-token",
            "deepgram_api_key": "old-dg",
            "tavily_api_key": "old-tv",
            "web_search_enabled": False,
        }
    )

    resp = client.post(
        "/api/settings",
        headers=auth_headers,
        json=_full_payload(
            cb_password="new-password",
            openai_api_key="new-openai",
            deepgram_api_key="new-dg",
            tavily_api_key="new-tv",
            web_search_enabled=True,
        ),
    )
    assert resp.status_code == 200, resp.text
    saved = settings_store.load_settings()
    assert saved["cb_password"] == "new-password"
    assert saved["openai_api_key"] == "new-openai"
    assert saved["deepgram_api_key"] == "new-dg"
    assert saved["tavily_api_key"] == "new-tv"
    assert saved["web_search_enabled"] is True


def test_save_settings_persists_blank_secret(client, auth_headers):
    """Explicitly blank input -> blank stored (the user opted the secret out)."""
    from services import settings_store

    settings_store.save_settings(
        {
            "cb_connection_string": "couchbase://localhost",
            "cb_username": "admin",
            "cb_password": "kept-password",
            "cb_bucket": "rag",
            "cb_scope": "_default",
            "cb_collection": "documents_local",
            "cb_search_index": "vector-search-index-local",
            "embedding_method": "python",
            "azure_openai_endpoint": "https://example.openai.azure.com",
            "openai_api_key": "kept-openai",
            "openai_realtime_model": "gpt-realtime",
            "openai_embedding_model": "text-embedding-3-small",
            "capella_api_key_id": "",
            "capella_api_key_token": "",
            "deepgram_api_key": "",
            "tavily_api_key": "stale-tv",
            "web_search_enabled": False,
        }
    )

    resp = client.post(
        "/api/settings",
        headers=auth_headers,
        json=_full_payload(
            cb_password="kept-password",
            openai_api_key="kept-openai",
            tavily_api_key="",  # explicit clear
        ),
    )
    assert resp.status_code == 200, resp.text
    assert settings_store.load_settings()["tavily_api_key"] == ""


def test_save_settings_persists_web_search_toggle(client, auth_headers):
    from services import settings_store

    resp = client.post(
        "/api/settings",
        headers=auth_headers,
        json=_full_payload(web_search_enabled=True),
    )
    assert resp.status_code == 200, resp.text
    assert settings_store.load_settings()["web_search_enabled"] is True

    resp = client.post(
        "/api/settings",
        headers=auth_headers,
        json=_full_payload(web_search_enabled=False),
    )
    assert resp.status_code == 200
    assert settings_store.load_settings()["web_search_enabled"] is False


def test_save_settings_rejects_invalid_embedding_method(client, auth_headers):
    resp = client.post(
        "/api/settings",
        headers=auth_headers,
        json=_full_payload(embedding_method="bogus"),
    )
    assert resp.status_code == 400


def test_save_settings_capella_mode_invokes_ensure_user_and_bucket(
    client, auth_headers, monkeypatch
):
    """capella mode + key set -> both ensure_user and ensure_bucket run."""
    from services import capella_management_service

    monkeypatch.setattr(
        capella_management_service.config.settings, "capella_api_key_id", "k"
    )
    monkeypatch.setattr(
        capella_management_service.config.settings, "capella_api_key_token", "t"
    )

    user_calls: list[tuple[str, str, str]] = []
    bucket_calls: list[tuple[str, int]] = []

    async def _fake_user(username: str, password: str, bucket: str) -> None:
        user_calls.append((username, password, bucket))

    async def _fake_bucket(name: str, ram_quota_mb: int = 256) -> None:
        bucket_calls.append((name, ram_quota_mb))

    monkeypatch.setattr(capella_management_service, "ensure_user", _fake_user)
    monkeypatch.setattr(capella_management_service, "ensure_bucket", _fake_bucket)

    resp = client.post(
        "/api/settings",
        headers=auth_headers,
        json=_full_payload(
            cb_username="rag_app",
            cb_password="rag_app_secret",
            cb_bucket="auto-rag",
            cb_collection="documents_capella",
            cb_search_index="vector-search-index-capella",
            embedding_method="capella",
            capella_api_key_id="k",
            capella_api_key_token="t",
        ),
    )
    assert resp.status_code == 200, resp.text
    assert user_calls == [("rag_app", "rag_app_secret", "auto-rag")]
    assert bucket_calls == [("auto-rag", 256)]


def test_save_settings_capella_mode_skips_when_no_api_key(
    client, auth_headers, monkeypatch
):
    """capella mode but no Capella API key -> ensure_* both skipped."""
    from services import capella_management_service

    monkeypatch.setattr(
        capella_management_service.config.settings, "capella_api_key_id", ""
    )
    monkeypatch.setattr(
        capella_management_service.config.settings, "capella_api_key_token", ""
    )

    user_called = False
    bucket_called = False

    async def _fake_user(username: str, password: str, bucket: str) -> None:
        nonlocal user_called
        user_called = True

    async def _fake_bucket(name: str, ram_quota_mb: int = 256) -> None:
        nonlocal bucket_called
        bucket_called = True

    monkeypatch.setattr(capella_management_service, "ensure_user", _fake_user)
    monkeypatch.setattr(capella_management_service, "ensure_bucket", _fake_bucket)

    resp = client.post(
        "/api/settings",
        headers=auth_headers,
        json=_full_payload(
            cb_collection="documents_capella",
            cb_search_index="vector-search-index-capella",
            embedding_method="capella",
        ),
    )
    assert resp.status_code == 200
    assert user_called is False
    assert bucket_called is False


def test_save_settings_python_mode_skips_capella_calls(
    client, auth_headers, monkeypatch
):
    """python mode -> never touch the Capella Management API."""
    from services import capella_management_service

    monkeypatch.setattr(
        capella_management_service.config.settings, "capella_api_key_id", "k"
    )
    monkeypatch.setattr(
        capella_management_service.config.settings, "capella_api_key_token", "t"
    )

    user_called = False
    bucket_called = False

    async def _fake_user(username: str, password: str, bucket: str) -> None:
        nonlocal user_called
        user_called = True

    async def _fake_bucket(name: str, ram_quota_mb: int = 256) -> None:
        nonlocal bucket_called
        bucket_called = True

    monkeypatch.setattr(capella_management_service, "ensure_user", _fake_user)
    monkeypatch.setattr(capella_management_service, "ensure_bucket", _fake_bucket)

    resp = client.post(
        "/api/settings",
        headers=auth_headers,
        json=_full_payload(),
    )
    assert resp.status_code == 200
    assert user_called is False
    assert bucket_called is False
