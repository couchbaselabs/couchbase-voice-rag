def test_health_returns_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_emits_request_id_header(client):
    resp = client.get("/api/health")
    assert "x-request-id" in resp.headers
    assert len(resp.headers["x-request-id"]) > 0


def test_client_supplied_request_id_is_honoured(client):
    resp = client.get("/api/health", headers={"X-Request-ID": "custom-id-42"})
    assert resp.headers["x-request-id"] == "custom-id-42"
