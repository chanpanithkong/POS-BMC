"""Accepts or creates an X-Correlation-Id and returns it on every response."""

import re
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import correlation_id

HEADER = b"x-correlation-id"
_VALID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class CorrelationIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(HEADER, b"").decode("latin-1")
        value = incoming if _VALID.match(incoming) else str(uuid.uuid4())
        token = correlation_id.set(value)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append((HEADER, value.encode("latin-1")))
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            correlation_id.reset(token)
