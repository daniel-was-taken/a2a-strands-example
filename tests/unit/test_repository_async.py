"""Unit tests for the async PostgresConversationStore.

These tests validate construction and shape of the async API without requiring
a live Postgres. The real end-to-end behaviour is covered by
``tests/test_store.py`` via the InMemory store (same protocol).
"""

from __future__ import annotations

import inspect

import pytest

from core.schemas import ActivityEvent, Conversation, Message
from db.repository import PostgresConversationStore


def test_all_store_methods_are_async():
    """Every public operation on PostgresConversationStore must be a coroutine."""
    store = PostgresConversationStore.__new__(PostgresConversationStore)
    for name in ("create", "get", "list_all", "add_message", "add_event",
                 "update", "delete", "startup", "shutdown", "ping"):
        method = getattr(store, name)
        assert inspect.iscoroutinefunction(method), f"{name} must be async"


def test_row_to_conversation_parses_json_columns():
    """Row helper should rehydrate message and event JSON arrays into models."""
    from db.repository import _row_to_conversation

    row = {
        "id": "abc",
        "title": "t",
        "status": "active",
        "approval_id": None,
        "review_verdict": None,
        "review_recommended_reject": False,
        "pending_query": None,
        "pending_brd_request": None,
        "evidence_summary": None,
        "messages": [{"role": "user", "content": "hi", "timestamp": "2024-01-01T00:00:00"}],
        "events": [{"agent": "orch", "action": "received", "detail": "d",
                    "timestamp": "2024-01-01T00:00:00"}],
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    }
    conv = _row_to_conversation(row)
    assert isinstance(conv, Conversation)
    assert len(conv.messages) == 1 and isinstance(conv.messages[0], Message)
    assert len(conv.events) == 1 and isinstance(conv.events[0], ActivityEvent)


def test_construction_requires_database_url(monkeypatch):
    """Instantiating without DATABASE_URL or an injected pool must raise."""
    from core import config as config_module

    monkeypatch.setattr(config_module.settings, "database_url", None)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        PostgresConversationStore()
