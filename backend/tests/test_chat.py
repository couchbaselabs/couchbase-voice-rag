def test_list_sessions_requires_auth(client):
    resp = client.get("/api/chat/sessions")
    assert resp.status_code == 401


def test_list_sessions_returns_array(client, auth_headers):
    resp = client.get("/api/chat/sessions", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_load_missing_session_returns_404(client, auth_headers):
    resp = client.get("/api/chat/sessions/nonexistent", headers=auth_headers)
    assert resp.status_code == 404


def test_load_existing_session(client, auth_headers, monkeypatch):
    from services import couchbase_service

    monkeypatch.setattr(
        couchbase_service,
        "load_chat_session",
        lambda sid: {
            "session_id": sid,
            "title": "Hello",
            "messages": [{"role": "user", "text": "hi"}],
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-02T00:00:00+00:00",
        },
    )
    resp = client.get("/api/chat/sessions/abc", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "abc"
    assert body["messages"] == [{"role": "user", "text": "hi"}]


def test_save_session_calls_service(client, auth_headers, mocker):
    from services import couchbase_service

    spy = mocker.patch.object(couchbase_service, "save_chat_session")
    resp = client.post(
        "/api/chat/sessions/abc",
        headers=auth_headers,
        json={"title": "t", "messages": [{"role": "user", "text": "hi"}]},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    spy.assert_called_once_with("abc", "t", [{"role": "user", "text": "hi"}])


def test_save_session_rejects_malformed_message(client, auth_headers):
    """ChatMessage requires role ∈ {user, assistant} and a string text field."""
    resp = client.post(
        "/api/chat/sessions/abc",
        headers=auth_headers,
        json={"title": "t", "messages": [{"role": "system", "text": "hi"}]},
    )
    assert resp.status_code == 422


def test_delete_session_calls_service(client, auth_headers, mocker):
    from services import couchbase_service

    spy = mocker.patch.object(couchbase_service, "delete_chat_session")
    resp = client.delete("/api/chat/sessions/abc", headers=auth_headers)
    assert resp.status_code == 200
    spy.assert_called_once_with("abc")
