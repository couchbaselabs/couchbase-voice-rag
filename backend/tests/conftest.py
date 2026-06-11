"""Test fixtures.

The app is imported once per test session but module-level state
(user_store / settings_store file paths, the slowapi limiter, and
Couchbase SDK calls) is patched per-test so tests stay hermetic.
"""

import os

os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("APP_USERS", "")
os.environ.setdefault("TAVILY_API_KEY", "")
os.environ.setdefault("DEEPGRAM_API_KEY", "")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_local_storage(tmp_path, monkeypatch):
    """Point user_store / settings_store at a fresh tmp directory per-test."""
    from services import settings_store, user_store

    monkeypatch.setattr(user_store, "USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setattr(settings_store, "SETTINGS_FILE", str(tmp_path / "settings.json"))


@pytest.fixture(autouse=True)
def stub_couchbase(monkeypatch):
    """Replace every Couchbase helper used by routes with an in-memory stub."""
    from services import couchbase_service

    monkeypatch.setattr(couchbase_service, "connect", lambda: None)
    monkeypatch.setattr(couchbase_service, "disconnect", lambda: None)
    monkeypatch.setattr(couchbase_service, "setup", lambda *args, **kwargs: None)
    monkeypatch.setattr(couchbase_service, "list_uploaded_files", lambda: [])
    monkeypatch.setattr(couchbase_service, "delete_documents_by_filename", lambda f: None)
    monkeypatch.setattr(couchbase_service, "list_chat_sessions", lambda: [])
    monkeypatch.setattr(couchbase_service, "load_chat_session", lambda sid: None)
    monkeypatch.setattr(couchbase_service, "save_chat_session", lambda sid, t, m: None)
    monkeypatch.setattr(couchbase_service, "delete_chat_session", lambda sid: None)
    monkeypatch.setattr(couchbase_service, "load_vocabulary_hints", lambda: [])
    monkeypatch.setattr(couchbase_service, "save_vocabulary_hints", lambda terms: None)


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Clear slowapi counters so parallel tests don't trip the 10/minute login cap."""
    from middleware.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def app():
    from main import app as fastapi_app

    return fastapi_app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def test_user():
    """Create a single known user in the isolated store and return its credentials."""
    from services import user_store

    user_store.set_password("tester", "testpass1234")
    return "tester", "testpass1234"


@pytest.fixture
def auth_headers(client, test_user):
    username, password = test_user
    resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}
