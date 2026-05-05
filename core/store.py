"""Conversation store — async protocol + in-memory implementation.

The orchestrator talks to one of two backends:

- ``InMemoryConversationStore`` (default)
- ``PostgresConversationStore`` (see ``db/repository.py``) when
  ``STORE_BACKEND=postgres`` and ``DATABASE_URL`` is configured.

Both implement the async :class:`ConversationStore` protocol so FastAPI
handlers can ``await`` store calls without blocking the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Protocol

from core.config import settings
from core.schemas import ActivityEvent, Conversation, Message

logger = logging.getLogger(__name__)


class ConversationStore(Protocol):
    """Abstract async interface for conversation persistence."""

    async def create(self, conversation: Conversation) -> None: ...
    async def get(self, conversation_id: str) -> Conversation | None: ...
    async def list_all(self) -> list[Conversation]: ...
    async def add_message(self, conversation_id: str, message: Message) -> None: ...
    async def add_event(self, conversation_id: str, event: ActivityEvent) -> None: ...
    async def update(self, conversation_id: str, **fields: Any) -> Conversation | None: ...
    async def delete(self, conversation_id: str) -> None: ...


class InMemoryConversationStore:
    """Async-safe dict-backed implementation of :class:`ConversationStore`."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._conversations: dict[str, Conversation] = {}

    async def create(self, conversation: Conversation) -> None:
        async with self._lock:
            self._conversations[conversation.id] = conversation

    async def get(self, conversation_id: str) -> Conversation | None:
        async with self._lock:
            return self._conversations.get(conversation_id)

    async def list_all(self) -> list[Conversation]:
        async with self._lock:
            return sorted(
                self._conversations.values(),
                key=lambda c: c.updated_at,
                reverse=True,
            )

    async def add_message(self, conversation_id: str, message: Message) -> None:
        async with self._lock:
            conv = self._conversations.get(conversation_id)
            if conv:
                conv.messages.append(message)
                conv.updated_at = datetime.now(UTC).isoformat()

    async def add_event(self, conversation_id: str, event: ActivityEvent) -> None:
        async with self._lock:
            conv = self._conversations.get(conversation_id)
            if conv:
                conv.events.append(event)

    async def update(self, conversation_id: str, **fields: Any) -> Conversation | None:
        async with self._lock:
            conv = self._conversations.get(conversation_id)
            if conv:
                for key, value in fields.items():
                    setattr(conv, key, value)
                conv.updated_at = datetime.now(UTC).isoformat()
                return conv
            return None

    async def delete(self, conversation_id: str) -> None:
        async with self._lock:
            self._conversations.pop(conversation_id, None)


def _create_store() -> ConversationStore:
    if settings.store_backend == "postgres":
        from db.repository import PostgresConversationStore

        if not settings.database_url:
            raise ValueError(
                "STORE_BACKEND=postgres requires DATABASE_URL to be configured"
            )
        logger.info("Using PostgresConversationStore (DATABASE_URL)")
        return PostgresConversationStore()
    logger.info("Using InMemoryConversationStore")
    return InMemoryConversationStore()


conversation_store: ConversationStore = _create_store()
