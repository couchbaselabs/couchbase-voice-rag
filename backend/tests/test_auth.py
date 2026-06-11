def test_login_with_valid_credentials(client, test_user):
    username, password = test_user
    resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == username
    assert body["token"]
    assert body["must_change_password"] is False


def test_login_with_wrong_password(client, test_user):
    username, _ = test_user
    resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": "wrong"},
    )
    assert resp.status_code == 401


def test_login_rejects_missing_user(client):
    resp = client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": "whatever"},
    )
    assert resp.status_code == 401


def test_me_requires_auth(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_returns_username(client, auth_headers):
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "tester"


def test_change_password_rejects_wrong_current(client, auth_headers):
    resp = client.post(
        "/api/auth/change-password",
        headers=auth_headers,
        json={"current_password": "wrong", "new_password": "newpass1234"},
    )
    assert resp.status_code == 401


def test_change_password_success_invalidates_tokens(client, auth_headers, test_user):
    _, password = test_user
    resp = client.post(
        "/api/auth/change-password",
        headers=auth_headers,
        json={"current_password": password, "new_password": "newpass1234"},
    )
    assert resp.status_code == 200

    # Old token must now be rejected because token_version was bumped.
    after = client.get("/api/auth/me", headers=auth_headers)
    assert after.status_code == 401


def test_force_logout_invalidates_existing_tokens(client, auth_headers):
    resp = client.post("/api/auth/force-logout", headers=auth_headers)
    assert resp.status_code == 200
    assert "version=" in resp.json()["message"]

    after = client.get("/api/auth/me", headers=auth_headers)
    assert after.status_code == 401


def test_login_rate_limit_trips_after_10(client):
    """11th login attempt inside a minute returns 429."""
    last_status = None
    for _ in range(11):
        resp = client.post(
            "/api/auth/login",
            json={"username": "nobody", "password": "whatever"},
        )
        last_status = resp.status_code
    assert last_status == 429
