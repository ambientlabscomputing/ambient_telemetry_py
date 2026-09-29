"""Starlette/FastAPI integration.

    app.add_middleware(TelemetryMiddleware)

Reads the per-tab session id the browser library sends in ``X-Ambient-Session`` and
binds it for the request, so an error raised in the API carries the same
``session_id`` as the frontend events that led to it. Bind the user once your auth
dependency has resolved them (``ambient_telemetry.bind(user_id=..., org_id=...)``).

Pure ASGI (not BaseHTTPMiddleware) so the bound context reaches the endpoint.
"""

from __future__ import annotations

import re
from typing import Any

from . import _context

SESSION_HEADER = b"x-ambient-session"
_VALID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class TelemetryMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket"):
            # Fresh context per request; never inherit a previous request's user.
            token = _context._ctx.set(_context.Context())
            try:
                for name, value in scope.get("headers", []):
                    if name == SESSION_HEADER:
                        session_id = value.decode("latin-1")
                        if _VALID.match(session_id):
                            _context.bind(session_id=session_id)
                        break
                await self.app(scope, receive, send)
            finally:
                _context._ctx.reset(token)
        else:
            await self.app(scope, receive, send)
