import pytest
from starlette.websockets import WebSocketDisconnect

ALLOWED = {"origin": "http://localhost:3000"}


def test_realtime_ws_rejects_missing_cookie(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/realtime", headers=ALLOWED):
            pass
    assert exc_info.value.code == 4001


def test_realtime_ws_rejects_invalid_cookie(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/ws/realtime",
            headers={**ALLOWED, "cookie": "token=not-a-jwt"},
        ):
            pass
    assert exc_info.value.code == 4001


def test_realtime_ws_ignores_query_param_token(client):
    """Cookie-only auth: a token supplied via query string must NOT let the WS through."""
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/realtime?token=something", headers=ALLOWED):
            pass
    assert exc_info.value.code == 4001


def test_deepgram_ws_rejects_missing_cookie(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/deepgram", headers=ALLOWED):
            pass
    assert exc_info.value.code == 4001


def test_realtime_ws_rejects_missing_origin(client):
    """A handshake with no Origin header (curl, native client, attacker probe)
    is rejected with 4003 before the cookie is even inspected."""
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/realtime"):
            pass
    assert exc_info.value.code == 4003


def test_realtime_ws_rejects_disallowed_origin(client):
    """CSWSH guard: a cross-site Origin not on the allowlist is rejected with 4003,
    even when the request carries a (notionally) valid auth cookie."""
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/ws/realtime",
            headers={"origin": "https://attacker.com", "cookie": "token=anything"},
        ):
            pass
    assert exc_info.value.code == 4003


def test_deepgram_ws_rejects_disallowed_origin(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/ws/deepgram",
            headers={"origin": "https://attacker.com"},
        ):
            pass
    assert exc_info.value.code == 4003
