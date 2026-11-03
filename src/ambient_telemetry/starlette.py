"""Starlette/FastAPI integration.

    app.add_middleware(TelemetryMiddleware)

Reads the per-tab session id the browser library sends in ``X-Ambient-Session`` and
binds it for the request, so an error raised in the API carries the same
``session_id`` as the frontend events that led to it. Bind the user once your auth
dependency has resolved them (``ambient_telemetry.bind(user_id=..., org_id=...)``).

It also binds the caller's public IP (used only when ``TelemetryConfig.capture_ip`` is on).
By default that is the ASGI peer address (``scope["client"]``), which uvicorn rewrites from
``X-Forwarded-For`` when you run it with ``--proxy-headers --forwarded-allow-ips=<proxy>``.
If your own proxy sets a single-address header you trust (``cf-connecting-ip``,
``x-real-ip``, ...), pass it as ``ip_header``. Never point ``ip_header`` at a header the
client can set itself; it would let anyone choose the IP your telemetry records.

Pure ASGI (not BaseHTTPMiddleware) so the bound context reaches the endpoint.
"""

from __future__ import annotations

import re
from typing import Any

from . import _context
from ._ip import public_ip

SESSION_HEADER = b"x-ambient-session"
_VALID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class TelemetryMiddleware:
    def __init__(self, app: Any, *, ip_header: str | None = None) -> None:
        self.app = app
        self._ip_header = ip_header.lower().encode("latin-1") if ip_header else None

    def _client_ip(self, scope: Any) -> str | None:
        if self._ip_header:
            for name, value in scope.get("headers", []):
                if name == self._ip_header:
                    # A proxy-appended list ("client, proxy1, proxy2"): the first is the client.
                    ip = public_ip(value.decode("latin-1").split(",")[0])
                    if ip:
                        return ip
                    break
        client = scope.get("client")
        return public_ip(client[0]) if client else None

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
                _context.bind(ip=self._client_ip(scope))
                await self.app(scope, receive, send)
            finally:
                _context._ctx.reset(token)
        else:
            await self.app(scope, receive, send)
