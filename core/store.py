"""In-memory conversation store.

Provides a thread-safe store for conversation records. Implements the
``ConversationStore`` protocol so it can be swapped for a persistent backend
(Redis, PostgreSQL, etc.) without changing calling code.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any, Protocol

from core.config import settings
from core.schemas import ActivityEvent, Conversation, Message

logger = logging.getLogger(__name__)


class ConversationStore(Protocol):
    """Abstract interface for conversation persistence."""

    def create(self, conversation: Conversation) -> None: ...
    def get(self, conversation_id: str) -> Conversation | None: ...
    def list_all(self) -> list[Conversation]: ...
    def add_message(self, conversation_id: str, message: Message) -> None: ...
    def add_event(self, conversation_id: str, event: ActivityEvent) -> None: ...
    def update(self, conversation_id: str, **fields: Any) -> Conversation | None: ...
    def delete(self, conversation_id: str) -> None: ...


class InMemoryConversationStore:
    """Thread-safe dict-backed implementation of :class:`ConversationStore`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._conversations: dict[str, Conversation] = {}

    def create(self, conversation: Conversation) -> None:
        with self._lock:
            self._conversations[conversation.id] = conversation

    def get(self, conversation_id: str) -> Conversation | None:
        with self._lock:
            return self._conversations.get(conversation_id)

    def list_all(self) -> list[Conversation]:
        with self._lock:
            return sorted(
                self._conversations.values(),
                key=lambda c: c.updated_at,
                reverse=True,
            )

    def add_message(self, conversation_id: str, message: Message) -> None:
        with self._lock:
            conv = self._conversations.get(conversation_id)
            if conv:
                conv.messages.append(message)
                conv.updated_at = datetime.now(UTC).isoformat()

    def add_event(self, conversation_id: str, event: ActivityEvent) -> None:
        with self._lock:
            conv = self._conversations.get(conversation_id)
            if conv:
                conv.events.append(event)

    def update(self, conversation_id: str, **fields: Any) -> Conversation | None:
        with self._lock:
            conv = self._conversations.get(conversation_id)
            if conv:
                for key, value in fields.items():
                    setattr(conv, key, value)
                conv.updated_at = datetime.now(UTC).isoformat()
                return conv
            return None

    def delete(self, conversation_id: str) -> None:
        with self._lock:
            self._conversations.pop(conversation_id, None)


def _create_store() -> ConversationStore:
    if settings.store_backend == "postgres":
        from db.repository import PostgresConversationStore

        logger.info("Using PostgresConversationStore (DATABASE_URL)")
        return PostgresConversationStore()
    logger.info("Using InMemoryConversationStore")
    return InMemoryConversationStore()


conversation_store: ConversationStore = _create_store()
