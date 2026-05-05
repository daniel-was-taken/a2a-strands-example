"""Request timing middleware and lightweight metric helpers.

The :class:`TimingMiddleware` records per-request wall-clock duration in the
log stream and exposes it to clients via the ``X-Response-Time-Ms`` header.
The ``record_operation`` context manager is used by ``db/neon.py`` and
``core/mcp.py`` to log operation-level timings in the same structured format.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class TimingMiddleware(BaseHTTPMiddleware):
    """Attach an ``X-Response-Time-Ms`` header and log duration per request."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        start = time.perf_counter()
        response: Response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"
        logger.info(
            "request_completed path=%s method=%s status=%d duration_ms=%.1f",
            request.url.path,
            request.method,
            response.status_code,
            duration_ms,
        )
        return response


@contextmanager
def record_operation(component: str, operation: str, **extra: Any) -> Iterator[dict[str, Any]]:
    """Context manager that logs ``component.operation`` duration on exit.

    Callers may mutate the yielded dict to attach additional metadata
    (e.g., HTTP status codes, retry counts). The final log line includes
    duration_ms and any attached metadata.
    """
    start = time.perf_counter()
    meta: dict[str, Any] = dict(extra)
    try:
        yield meta
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        meta["error"] = type(exc).__name__
        logger.warning(
            "%s.%s failed duration_ms=%.1f meta=%s",
            component,
            operation,
            duration_ms,
            meta,
        )
        raise
    else:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s.%s duration_ms=%.1f meta=%s",
            component,
            operation,
            duration_ms,
            meta,
        )
