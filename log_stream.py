"""Server-Sent Events log stream.

Broadcasts structured log records to connected SSE clients.  Install the
``SseHandler`` via :func:`install` during application lifespan so that any
``logging`` call is forwarded to all active SSE connections.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager


class SseBroadcaster:
    """Fan-out queue that pushes log messages to all connected SSE clients."""

    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[str]] = set()

    def publish(self, data: str) -> None:
        for q in list(self._queues):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass  # drop oldest if consumer can't keep up

    @asynccontextmanager
    async def subscribe(self) -> AsyncGenerator[asyncio.Queue[str]]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        self._queues.add(q)
        try:
            yield q
        finally:
            self._queues.discard(q)


class SseHandler(logging.Handler):
    """Logging handler that publishes formatted records to the SSE broadcaster."""

    def __init__(self, broadcaster: SseBroadcaster) -> None:
        super().__init__()
        self._broadcaster = broadcaster

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = json.dumps({
                "timestamp": self.format(record).split(" ")[0] if " " in self.format(record) else "",
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            })
            self._broadcaster.publish(payload)
        except Exception:
            self.handleError(record)


# Module-level singleton
broadcaster = SseBroadcaster()


def install(level: int = logging.INFO) -> SseHandler:
    """Attach the SSE handler to the root logger and return it."""
    handler = SseHandler(broadcaster)
    handler.setLevel(level)
    logging.getLogger().addHandler(handler)
    return handler
