"""Request-ID ASGI middleware.

A ``ContextVar`` holds the current request's id so log records emitted
from any task spawned during the request (handlers, background tasks,
awaited I/O) can attach it without explicit plumbing. The middleware
echoes the id back via the ``X-Request-ID`` response header.
"""

import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Receive, Scope, Send

REQUEST_ID_HEADER = "x-request-id"

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIDMiddleware:
    """Attach a request id to every HTTP request and its log output."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        incoming = _extract_header(scope, REQUEST_ID_HEADER)
        request_id = incoming or uuid.uuid4().hex
        token = request_id_var.set(request_id)

        async def send_with_header(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append(
                    (REQUEST_ID_HEADER.encode(), request_id.encode())
                )
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            request_id_var.reset(token)


def _extract_header(scope: Scope, name: str) -> str | None:
    wanted = name.lower().encode()
    for key, value in scope.get("headers") or []:
        if key.lower() == wanted:
            return value.decode(errors="replace")
    return None
