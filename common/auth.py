"""Authentication middleware for A2A agent FastAPI/Starlette apps.

Validates the ``X-Agent-API-Key`` header on all incoming requests.
Set ``AGENT_API_KEY`` to a shared secret to enable; leave empty to disable
(e.g. during local development behind a VPN).

Paths listed in ``_EXEMPT_PATHS`` bypass auth so that agent discovery
(``/.well-known/agent-card.json``) and health checks always succeed.

Usage::

    app = a2a_server.to_fastapi_app()
    app.add_middleware(AgentAuthMiddleware, api_key=settings.agent_api_key)
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Paths that must remain publicly accessible regardless of auth config.
_EXEMPT_PATHS: frozenset[str] = frozenset({"/.well-known/agent-card.json", "/health", "/ready"})


class AgentAuthMiddleware(BaseHTTPMiddleware):
    """Reject requests that lack a valid ``X-Agent-API-Key`` header.

    When ``api_key`` is empty the middleware is a transparent pass-through,
    which makes it safe to unconditionally add to every server.
    """

    def __init__(self, app, *, api_key: str) -> None:
        super().__init__(app)
        self._api_key = api_key

    async def dispatch(self, request: Request, call_next):
        # Auth disabled — pass through.
        if not self._api_key:
            return await call_next(request)

        # Exempt paths — pass through.
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        provided = request.headers.get("x-agent-api-key", "")
        if provided != self._api_key:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "unauthorized",
                    "detail": "Invalid or missing X-Agent-API-Key header",
                },
            )
        return await call_next(request)
