# Conversation-First UI Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat query-list UI with a ChatGPT-style conversation interface, fix agent memory leaking across conversations, and introduce a proper conversation data model.

**Architecture:** Data model shifts from `QueryResponse` to `Conversation`. The agent singleton is kept but its `messages` array is reset before each turn, with context rebuilt from the conversation's stored messages. Frontend becomes a ChatGPT-style chat app with conversations in a sidebar, "New Chat" button, and inline approval dialogs.

**Tech Stack:** Python 3.11+, FastAPI, Strands Agents SDK, vanilla JS (no build step), Pydantic

**Spec:** `docs/superpowers/specs/2026-03-31-conversation-ui-redesign.md`

---

### Task 1: Data Models

**Files:**
- Modify: `common/schemas.py`
- Create: `tests/unit/test_schemas.py`

- [ ] **Step 1: Write failing tests for new models**

```python
# tests/unit/test_schemas.py
"""Tests for the conversation data models."""

from common.schemas import (
    ActivityEvent,
    Conversation,
    ConversationStatus,
    ConversationSummary,
    Message,
    MessageRequest,
)


def test_conversation_defaults():
    conv = Conversation(id="c1", title="Test")
    assert conv.status == ConversationStatus.ACTIVE
    assert conv.messages == []
    assert conv.events == []
    assert conv.approval_id is None
    assert conv.review_verdict is None
    assert conv.review_recommended_reject is False
    assert conv.pending_query is None
    assert conv.created_at  # auto-generated
    assert conv.updated_at  # auto-generated


def test_conversation_with_messages():
    conv = Conversation(
        id="c1",
        title="Test",
        messages=[Message(role="user", content="hello")],
    )
    assert len(conv.messages) == 1
    assert conv.messages[0].role == "user"


def test_conversation_awaiting_approval():
    conv = Conversation(
        id="c1",
        title="Test",
        status=ConversationStatus.AWAITING_APPROVAL,
        approval_id="abc123",
        review_verdict="APPROVE: scoped",
        pending_query="delete from users where id = 5",
    )
    assert conv.status == ConversationStatus.AWAITING_APPROVAL
    assert conv.approval_id == "abc123"


def test_conversation_summary():
    s = ConversationSummary(
        id="c1",
        title="Test",
        status=ConversationStatus.ACTIVE,
        created_at="2024-01-01T00:00:00",
        updated_at="2024-01-01T00:00:00",
    )
    assert s.id == "c1"
    assert s.title == "Test"


def test_message_request_valid():
    m = MessageRequest(content="hello")
    assert m.content == "hello"


def test_message_request_empty_rejected():
    import pytest

    with pytest.raises(Exception):
        MessageRequest(content="")


def test_message_unchanged():
    """Message model keeps role/content/timestamp fields."""
    m = Message(role="user", content="test")
    assert m.role == "user"
    assert m.content == "test"
    assert m.timestamp  # auto-generated


def test_activity_event_unchanged():
    """ActivityEvent model stays the same."""
    e = ActivityEvent(agent="orchestrator", action="received", detail="test")
    assert e.agent == "orchestrator"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_schemas.py -v`
Expected: FAIL — `ConversationStatus`, `Conversation`, `ConversationSummary`, `MessageRequest` not found

- [ ] **Step 3: Replace models in schemas.py**

```python
# common/schemas.py
"""Request/response schemas for the orchestrator API."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    AWAITING_APPROVAL = "awaiting_approval"


class ActivityEvent(BaseModel):
    """Single event in the activity log for a conversation."""

    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    agent: str
    action: str
    detail: str = ""


class Message(BaseModel):
    """Single message in a conversation thread."""

    role: Literal["user", "agent"]
    content: str
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class MessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)


class Conversation(BaseModel):
    id: str
    title: str
    status: ConversationStatus = ConversationStatus.ACTIVE
    approval_id: str | None = None
    review_verdict: str | None = None
    review_recommended_reject: bool = False
    pending_query: str | None = None
    messages: list[Message] = Field(default_factory=list)
    events: list[ActivityEvent] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ConversationSummary(BaseModel):
    id: str
    title: str
    status: ConversationStatus
    created_at: str
    updated_at: str


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_schemas.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add common/schemas.py tests/unit/test_schemas.py
git commit -m "feat: replace QueryResponse with Conversation data model"
```

---

### Task 2: ConversationStore

**Files:**
- Modify: `common/store.py`
- Modify: `tests/test_store.py`

- [ ] **Step 1: Write failing tests for new store**

```python
# tests/test_store.py
"""Tests for the InMemoryConversationStore."""

from common.schemas import ActivityEvent, Conversation, ConversationStatus, Message
from common.store import InMemoryConversationStore


def test_create_and_get():
    store = InMemoryConversationStore()
    conv = Conversation(id="c1", title="Test")
    store.create(conv)
    assert store.get("c1") is not None
    assert store.get("c1").title == "Test"


def test_get_missing_returns_none():
    store = InMemoryConversationStore()
    assert store.get("missing") is None


def test_list_all_ordered_by_updated_at():
    store = InMemoryConversationStore()
    c1 = Conversation(
        id="c1", title="First", updated_at="2024-01-01T00:00:00"
    )
    c2 = Conversation(
        id="c2", title="Second", updated_at="2024-01-02T00:00:00"
    )
    store.create(c1)
    store.create(c2)
    result = store.list_all()
    assert len(result) == 2
    assert result[0].id == "c2"  # newest first


def test_add_message():
    store = InMemoryConversationStore()
    store.create(Conversation(id="c1", title="T"))
    store.add_message("c1", Message(role="user", content="hello"))
    conv = store.get("c1")
    assert len(conv.messages) == 1
    assert conv.messages[0].content == "hello"


def test_add_message_updates_updated_at():
    store = InMemoryConversationStore()
    conv = Conversation(id="c1", title="T", updated_at="2024-01-01T00:00:00")
    store.create(conv)
    store.add_message("c1", Message(role="user", content="hello"))
    updated = store.get("c1")
    assert updated.updated_at != "2024-01-01T00:00:00"


def test_add_event():
    store = InMemoryConversationStore()
    store.create(Conversation(id="c1", title="T"))
    store.add_event("c1", ActivityEvent(agent="test", action="did"))
    conv = store.get("c1")
    assert len(conv.events) == 1
    assert conv.events[0].agent == "test"


def test_update():
    store = InMemoryConversationStore()
    store.create(Conversation(id="c1", title="T"))
    result = store.update(
        "c1", title="New Title", status=ConversationStatus.AWAITING_APPROVAL
    )
    assert result is not None
    assert result.title == "New Title"
    assert result.status == ConversationStatus.AWAITING_APPROVAL


def test_update_missing_returns_none():
    store = InMemoryConversationStore()
    assert store.update("missing", title="X") is None


def test_update_updates_updated_at():
    store = InMemoryConversationStore()
    conv = Conversation(id="c1", title="T", updated_at="2024-01-01T00:00:00")
    store.create(conv)
    store.update("c1", title="X")
    assert store.get("c1").updated_at != "2024-01-01T00:00:00"


def test_delete():
    store = InMemoryConversationStore()
    store.create(Conversation(id="c1", title="T"))
    store.delete("c1")
    assert store.get("c1") is None


def test_delete_missing_does_not_raise():
    store = InMemoryConversationStore()
    store.delete("missing")  # should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_store.py -v`
Expected: FAIL — `InMemoryConversationStore` not found

- [ ] **Step 3: Replace store implementation**

```python
# common/store.py
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

from .config import settings
from .schemas import ActivityEvent, Conversation, Message

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_store.py -v`
Expected: All 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add common/store.py tests/test_store.py
git commit -m "feat: replace QueryStore with ConversationStore"
```

---

### Task 3: Test Infrastructure

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Update conftest fixtures for new store**

```python
# tests/conftest.py
"""Configuration and fixtures for tests.

Run:  pytest tests/ -v
"""

import os
import tempfile
from pathlib import Path

# Set test defaults BEFORE any module imports trigger Settings() creation.
os.environ.setdefault("DATABASE_MODE", "direct")
os.environ.setdefault("GOOGLE_API_KEY", "test-google-key")

from unittest.mock import MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

# ── Test agents.yaml ─────────────────────────────────────────────────────────

_TEST_AGENTS_CONFIG = {
    "agents": [
        {
            "name": "Test MCP Agent",
            "type": "mcp",
            "port": 9001,
            "description": "Test database agent",
            "mcp_url": "https://example.com/mcp",
            "tools": ["tool_a"],
            "system_prompt": "You are a test agent.",
            "skills": [
                {
                    "id": "test-skill",
                    "name": "Test",
                    "description": "A test skill",
                    "tags": ["test"],
                }
            ],
        },
    ]
}

# Write test config to a temp file at import time so settings can reference it.
_test_config_dir = tempfile.mkdtemp()
_test_config_path = str(Path(_test_config_dir) / "agents.yaml")
Path(_test_config_path).write_text(yaml.dump(_TEST_AGENTS_CONFIG))
os.environ.setdefault("AGENTS_CONFIG", _test_config_path)


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch):
    """Ensure required env vars are set for tests (runtime reads)."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("DATABASE_MODE", "direct")
    monkeypatch.setenv("AGENTS_CONFIG", _test_config_path)


@pytest.fixture(autouse=True)
def _clear_store():
    """Reset the in-memory store between tests."""
    from common.store import conversation_store

    conversation_store._conversations.clear()


@pytest.fixture(autouse=True)
def _reset_agent():
    """Reset the lazy-loaded agent singleton between tests."""
    import agents.orchestrator_agent as orch

    orch._agent = None
    yield
    orch._agent = None


def _make_mock_agents(review_return):
    """Shared helper to build mock patches with a given review_delete_request return."""
    mock_agent = MagicMock(return_value="Test agent response")
    mock_agent.messages = []

    mock_model = MagicMock()

    return (
        mock_agent,
        patch("agents.model.create_model", return_value=mock_model),
        patch("agents.mcp_agent.create_mcp_agent", return_value=mock_agent),
        patch(
            "agents.orchestrator_agent.create_safety_reviewer",
            return_value=mock_agent,
        ),
        patch(
            "agents.orchestrator_agent.review_delete_request",
            return_value=review_return,
        ),
    )


@pytest.fixture()
def mock_agents():
    """Patch with safety reviewer that REJECTS destructive queries."""
    mock_agent, *patches = _make_mock_agents((False, "REJECT: test rejection"))
    with patches[0], patches[1], patches[2], patches[3]:
        yield mock_agent


@pytest.fixture()
def mock_agents_approve():
    """Patch with safety reviewer that APPROVES destructive queries."""
    mock_agent, *patches = _make_mock_agents((True, "APPROVE: clearly scoped request"))
    with patches[0], patches[1], patches[2], patches[3]:
        yield mock_agent


@pytest.fixture()
def client(mock_agents):
    """TestClient with fully mocked backend (safety reviewer rejects)."""
    from agents.orchestrator_agent import app

    yield TestClient(app)


@pytest.fixture()
def client_approve(mock_agents_approve):
    """TestClient with fully mocked backend (safety reviewer approves)."""
    from agents.orchestrator_agent import app

    yield TestClient(app)
```

- [ ] **Step 2: Verify no import errors**

Run: `python -c "from tests.conftest import _TEST_AGENTS_CONFIG; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "refactor: update test fixtures for ConversationStore"
```

---

### Task 4: Orchestrator Rewrite

**Files:**
- Modify: `agents/orchestrator_agent.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write all orchestrator tests**

```python
# tests/test_orchestrator.py
"""Tests for the orchestrator conversation lifecycle."""


# ── Conversation CRUD ──────────────────────────────────────────────────────


def test_create_conversation(client):
    """POST /conversations should create an empty conversation."""
    resp = client.post("/conversations")
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"]
    assert data["title"] == "New conversation"
    assert data["status"] == "active"
    assert data["messages"] == []
    assert data["events"] == []


def test_list_conversations_empty(client):
    resp = client.get("/conversations")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_conversations_returns_summaries(client):
    """GET /conversations should return summaries without messages."""
    client.post("/conversations")
    resp = client.get("/conversations")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "New conversation"
    assert "messages" not in data[0]
    assert "events" not in data[0]


def test_get_conversation(client):
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    resp = client.get(f"/conversations/{conv_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == conv_id
    assert "messages" in resp.json()


def test_get_conversation_not_found(client):
    resp = client.get("/conversations/nonexistent")
    assert resp.status_code == 404


def test_delete_conversation(client):
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    resp = client.delete(f"/conversations/{conv_id}")
    assert resp.status_code == 204
    assert client.get(f"/conversations/{conv_id}").status_code == 404


def test_delete_conversation_not_found(client):
    resp = client.delete("/conversations/nonexistent")
    assert resp.status_code == 404


# ── Message sending ────────────────────────────────────────────────────────


def test_send_message(client):
    """Non-destructive message should get an agent response."""
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    resp = client.post(
        f"/conversations/{conv_id}/messages", json={"content": "Show all tables"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    assert len(data["messages"]) == 2
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][0]["content"] == "Show all tables"
    assert data["messages"][1]["role"] == "agent"


def test_send_message_updates_title(client):
    """First message should set the conversation title."""
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    client.post(
        f"/conversations/{conv_id}/messages",
        json={"content": "Show all tables in the database"},
    )
    resp = client.get(f"/conversations/{conv_id}")
    assert resp.json()["title"] == "Show all tables in the database"


def test_send_message_title_truncated(client):
    """Long first message should be truncated to 50 chars in title."""
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    long_msg = "A" * 80
    client.post(f"/conversations/{conv_id}/messages", json={"content": long_msg})
    resp = client.get(f"/conversations/{conv_id}")
    title = resp.json()["title"]
    assert len(title) == 53  # 50 chars + "..."
    assert title.endswith("...")


def test_send_message_not_found(client):
    resp = client.post(
        "/conversations/nonexistent/messages", json={"content": "hello"}
    )
    assert resp.status_code == 404


def test_send_empty_message_returns_422(client):
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    resp = client.post(f"/conversations/{conv_id}/messages", json={"content": ""})
    assert resp.status_code == 422


def test_send_message_to_awaiting_returns_409(client_approve):
    """Cannot send messages while conversation is awaiting approval."""
    create_resp = client_approve.post("/conversations")
    conv_id = create_resp.json()["id"]
    client_approve.post(
        f"/conversations/{conv_id}/messages",
        json={"content": "delete from users where id = 5"},
    )
    resp = client_approve.post(
        f"/conversations/{conv_id}/messages", json={"content": "hello"}
    )
    assert resp.status_code == 409


def test_multi_turn_conversation(client):
    """Multiple messages should accumulate in the thread."""
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    client.post(
        f"/conversations/{conv_id}/messages", json={"content": "Show all tables"}
    )
    resp = client.post(
        f"/conversations/{conv_id}/messages", json={"content": "How many rows?"}
    )
    data = resp.json()
    assert len(data["messages"]) == 4  # 2 per turn


def test_agent_context_isolation(client):
    """Messages from conversation A must not leak into conversation B."""
    # Conversation A
    create_a = client.post("/conversations")
    conv_a_id = create_a.json()["id"]
    client.post(
        f"/conversations/{conv_a_id}/messages", json={"content": "Show all tables"}
    )

    # Conversation B
    create_b = client.post("/conversations")
    conv_b_id = create_b.json()["id"]
    resp = client.post(
        f"/conversations/{conv_b_id}/messages", json={"content": "Count employees"}
    )

    # Conv B should only have its own messages
    data = resp.json()
    assert len(data["messages"]) == 2
    assert data["messages"][0]["content"] == "Count employees"


# ── Destructive queries & approval ─────────────────────────────────────────


def test_destructive_message_recommended_reject(client):
    """Safety reviewer rejection should set awaiting_approval + recommended_reject."""
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    resp = client.post(
        f"/conversations/{conv_id}/messages",
        json={"content": "delete all employees"},
    )
    data = resp.json()
    assert data["status"] == "awaiting_approval"
    assert data["review_recommended_reject"] is True
    assert data["review_verdict"]
    assert data["pending_query"] == "delete all employees"


def test_destructive_message_pending_approval(client_approve):
    """Safety reviewer approval should set awaiting_approval without recommended_reject."""
    create_resp = client_approve.post("/conversations")
    conv_id = create_resp.json()["id"]
    resp = client_approve.post(
        f"/conversations/{conv_id}/messages",
        json={"content": "delete from users where id = 5"},
    )
    data = resp.json()
    assert data["status"] == "awaiting_approval"
    assert data["review_recommended_reject"] is False
    assert "APPROVE" in data["review_verdict"]
    assert data["approval_id"] is not None


def test_approve_conversation(client_approve):
    """Approving should execute the query and return to active."""
    create_resp = client_approve.post("/conversations")
    conv_id = create_resp.json()["id"]
    client_approve.post(
        f"/conversations/{conv_id}/messages",
        json={"content": "delete from users where id = 5"},
    )
    resp = client_approve.post(f"/conversations/{conv_id}/approve")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    assert data["approval_id"] is None
    assert data["pending_query"] is None
    assert any(m["role"] == "agent" and m["content"] != "" for m in data["messages"])


def test_reject_conversation(client_approve):
    """Rejecting should add rejection message and return to active."""
    create_resp = client_approve.post("/conversations")
    conv_id = create_resp.json()["id"]
    client_approve.post(
        f"/conversations/{conv_id}/messages",
        json={"content": "delete from users where id = 5"},
    )
    resp = client_approve.post(f"/conversations/{conv_id}/reject")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    assert data["approval_id"] is None
    assert data["messages"][-1]["content"] == "Query rejected by user."


def test_approve_not_awaiting_returns_409(client):
    """Cannot approve a conversation that is not awaiting approval."""
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    resp = client.post(f"/conversations/{conv_id}/approve")
    assert resp.status_code == 409


def test_approve_not_found(client):
    resp = client.post("/conversations/nonexistent/approve")
    assert resp.status_code == 404


def test_reject_not_found(client):
    resp = client.post("/conversations/nonexistent/reject")
    assert resp.status_code == 404


# ── Activity events ────────────────────────────────────────────────────────


def test_message_has_events(client):
    """Processed message should have activity events."""
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    client.post(
        f"/conversations/{conv_id}/messages", json={"content": "Show all tables"}
    )
    resp = client.get(f"/conversations/{conv_id}")
    events = resp.json()["events"]
    assert len(events) >= 2
    assert events[0]["agent"] == "orchestrator"
    assert events[0]["action"] == "received"


def test_destructive_message_has_review_events(client):
    """Destructive message should have safety review events."""
    create_resp = client.post("/conversations")
    conv_id = create_resp.json()["id"]
    client.post(
        f"/conversations/{conv_id}/messages",
        json={"content": "delete all employees"},
    )
    resp = client.get(f"/conversations/{conv_id}")
    events = resp.json()["events"]
    actions = [e["action"] for e in events]
    assert "review_started" in actions
    assert "review_completed" in actions


# ── Health & infrastructure ────────────────────────────────────────────────


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readiness_probe(client):
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_log_stream_endpoint_is_registered(client):
    routes = [r.path for r in client.app.routes if hasattr(r, "path")]
    assert "/logs/stream" in routes
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py -v`
Expected: FAIL — old endpoints still exist, new endpoints not found

- [ ] **Step 3: Write the complete orchestrator**

```python
# agents/orchestrator_agent.py
"""Orchestrator Agent -- FastAPI app on port 8000.

Receives user requests via REST and routes them to specialist agents
(declared in agents.yaml) via the A2A protocol.  Includes a safety
review step for destructive queries.
"""

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import token_hex
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import StreamingResponse
from strands import Agent

from agents.model import create_model
from common.config import settings
from common.log_stream import broadcaster
from common.log_stream import install as install_sse_handler
from common.schemas import (
    ActivityEvent,
    Conversation,
    ConversationStatus,
    ConversationSummary,
    ErrorResponse,
    HealthResponse,
    Message,
    MessageRequest,
)
from common.store import conversation_store
from tools.safety_reviewer import create_safety_reviewer, review_delete_request

logger = logging.getLogger(__name__)

DESTRUCTIVE_KEYWORDS = {"delete", "remove", "drop", "truncate", "destroy"}

MAX_THREAD_MESSAGES = 20


def _load_agents_config() -> list[dict]:
    """Load agents list from the YAML config file."""
    from agents.mcp_agent import load_agents_config

    return load_agents_config(settings.agents_config)


def _agent_url(cfg: dict) -> str:
    """Derive the A2A URL for an agent from its config."""
    host = cfg.get("host", "localhost")
    return f"http://{host}:{cfg['port']}/"


def _build_agent_urls(agents_config: list[dict]) -> list[str]:
    return [_agent_url(cfg) for cfg in agents_config]


def _build_agent_names(agents_config: list[dict]) -> dict[str, str]:
    return {_agent_url(cfg): cfg["name"] for cfg in agents_config}


def _build_system_prompt(agents_config: list[dict]) -> str:
    agent_lines = []
    for cfg in agents_config:
        url = _agent_url(cfg)
        desc = cfg.get("description", cfg["name"])
        agent_lines.append(f'- **{cfg["name"]}** (target_agent_url: "{url}")\n  {desc}')

    agents_block = "\n\n".join(agent_lines)
    return f"""You are the Orchestrator Agent. You receive requests from users and route them
to the appropriate specialist agent using the a2a_send_message tool.

Available agents (use these EXACT URLs with a2a_send_message):

{agents_block}

IMPORTANT: When calling a2a_send_message, you MUST use the exact target_agent_url
values listed above. Do NOT invent or guess URLs.

When asked what agents are available, list all connected agents and their capabilities.
Keep responses clear and relay the results back accurately.
"""


# ── Lazy-loaded agent singleton ──────────────────────────────────────

_agent_lock = threading.Lock()
_agent: Agent | None = None


def _get_agent() -> Agent:
    global _agent
    if _agent is not None:
        return _agent
    with _agent_lock:
        if _agent is not None:
            return _agent
        if settings.database_mode == "a2a":
            from strands_tools.a2a_client import A2AClientToolProvider

            agents_config = _load_agents_config()
            known_urls = _build_agent_urls(agents_config)
            provider = A2AClientToolProvider(known_agent_urls=known_urls)
            _agent = Agent(
                model=create_model(),
                system_prompt=_build_system_prompt(agents_config),
                tools=provider.tools,
            )
        else:
            from agents.mcp_agent import create_mcp_agent, load_agents_config

            agents_config = load_agents_config(settings.agents_config)
            mcp_agents = [a for a in agents_config if a["type"] == "mcp"]
            if mcp_agents:
                _agent = create_mcp_agent(mcp_agents[0])
            else:
                raise RuntimeError("No MCP agents found in config for direct mode")
        return _agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    install_sse_handler()
    logger.info("Starting Orchestrator (mode=%s)", settings.database_mode)
    yield
    logger.info("Shutting down Orchestrator")


limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])


app = FastAPI(
    title="A2A Database Orchestrator",
    description="Orchestrator agent that routes queries to specialist agents via A2A protocol",
    lifespan=lifespan,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content=ErrorResponse(error="rate_limited", detail="Too many requests").model_dump(),
    )


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    exempt_paths = ("/health", "/ready", "/", "/docs", "/openapi.json")
    if (
        settings.api_key
        and request.url.path not in exempt_paths
        and not request.url.path.startswith("/static")
    ):
        key = request.headers.get("x-api-key", "")
        if key != settings.api_key:
            body = ErrorResponse(
                error="unauthorized", detail="Invalid or missing API key"
            ).model_dump()
            return JSONResponse(status_code=401, content=body)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if _FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_FRONTEND_DIR)), name="static")


def _needs_safety_review(user_input: str) -> bool:
    words = set(user_input.lower().split())
    return bool(words & DESTRUCTIVE_KEYWORDS)


def _add_event(conversation_id: str, agent: str, action: str, detail: str = "") -> None:
    conversation_store.add_event(
        conversation_id,
        ActivityEvent(agent=agent, action=action, detail=detail),
    )


def _extract_routed_agents(agent: Agent) -> list[str]:
    try:
        agents_config = _load_agents_config()
        agent_names = _build_agent_names(agents_config)
    except Exception:
        agent_names = {}

    agents_used = []
    for msg in reversed(agent.messages):
        for block in msg.get("content", []):
            if isinstance(block, dict) and "toolUse" in block:
                tool = block["toolUse"]
                if tool.get("name") == "a2a_send_message":
                    url = tool.get("input", {}).get("target_agent_url", "")
                    name = agent_names.get(url, url)
                    if name not in agents_used:
                        agents_used.append(name)
    return agents_used


async def _execute_message(conversation_id: str) -> Conversation:
    """Reset agent context, rebuild from conversation messages, execute, store response."""
    conv = conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    _add_event(conversation_id, "orchestrator", "forwarding", "Routing to specialist agent")
    try:
        agent = _get_agent()
        agent.messages = []  # Clean slate — no cross-conversation leakage

        recent = conv.messages[-MAX_THREAD_MESSAGES:]
        if len(recent) <= 1:
            prompt = recent[0].content
        else:
            context_parts = []
            for msg in recent:
                label = "User" if msg.role == "user" else "Agent"
                context_parts.append(f"{label}: {msg.content}")
            prompt = "Previous conversation:\n" + "\n".join(context_parts)

        result = await asyncio.to_thread(agent, prompt)
        response = str(result)

        routed = _extract_routed_agents(agent)
        for name in routed:
            _add_event(
                conversation_id,
                name.lower().replace(" ", "_"),
                "executed",
                f"Handled by {name}",
            )

        _add_event(conversation_id, "orchestrator", "completed", "Message processed successfully")
        conversation_store.add_message(
            conversation_id, Message(role="agent", content=response)
        )
        return conversation_store.get(conversation_id)  # type: ignore[return-value]
    except Exception:
        logger.exception("Message execution failed for conversation %s", conversation_id)
        _add_event(conversation_id, "orchestrator", "failed", "Message execution failed")
        conversation_store.add_message(
            conversation_id,
            Message(role="agent", content="Something went wrong. Please try again."),
        )
        return conversation_store.get(conversation_id)  # type: ignore[return-value]


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/ready", response_model=HealthResponse)
def readiness() -> HealthResponse:
    try:
        _get_agent()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return HealthResponse()


@app.get("/logs/stream")
async def log_stream():
    async def _generate():
        async with broadcaster.subscribe() as queue:
            while True:
                data = await queue.get()
                yield f"data: {data}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


@app.post("/conversations", response_model=Conversation, status_code=201)
def create_conversation() -> Conversation:
    conv = Conversation(id=str(uuid4()), title="New conversation")
    conversation_store.create(conv)
    return conv


@app.get("/conversations", response_model=list[ConversationSummary])
def list_conversations() -> list[ConversationSummary]:
    conversations = conversation_store.list_all()
    return [
        ConversationSummary(
            id=c.id,
            title=c.title,
            status=c.status,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in conversations
    ]


@app.get("/conversations/{conversation_id}", response_model=Conversation)
def get_conversation(conversation_id: str) -> Conversation:
    conv = conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@app.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str) -> None:
    conv = conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation_store.delete(conversation_id)


@app.post("/conversations/{conversation_id}/messages", response_model=Conversation)
async def send_message(conversation_id: str, payload: MessageRequest) -> Conversation:
    conv = conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.status == ConversationStatus.AWAITING_APPROVAL:
        raise HTTPException(status_code=409, detail="Conversation is awaiting approval")

    content = payload.content
    conversation_store.add_message(conversation_id, Message(role="user", content=content))

    # Update title from first message
    conv = conversation_store.get(conversation_id)  # type: ignore[assignment]
    if conv.title == "New conversation":
        title = content[:50] + ("..." if len(content) > 50 else "")
        conversation_store.update(conversation_id, title=title)

    _add_event(conversation_id, "orchestrator", "received", f"Message received: {content[:120]}")

    if _needs_safety_review(content):
        _add_event(
            conversation_id, "safety_reviewer", "review_started", "Evaluating destructive query"
        )
        safety_reviewer = create_safety_reviewer()
        is_approved, verdict = review_delete_request(safety_reviewer, content)
        _add_event(conversation_id, "safety_reviewer", "review_completed", verdict)

        approval_id = token_hex(4)
        if not is_approved:
            conversation_store.update(
                conversation_id,
                status=ConversationStatus.AWAITING_APPROVAL,
                review_verdict=verdict,
                review_recommended_reject=True,
                pending_query=content,
                approval_id=approval_id,
            )
            _add_event(
                conversation_id,
                "orchestrator",
                "recommended_reject",
                "Safety reviewer recommends rejection",
            )
        else:
            conversation_store.update(
                conversation_id,
                status=ConversationStatus.AWAITING_APPROVAL,
                review_verdict=verdict,
                review_recommended_reject=False,
                pending_query=content,
                approval_id=approval_id,
            )
            _add_event(
                conversation_id, "orchestrator", "pending_approval", "Awaiting human confirmation"
            )

        return conversation_store.get(conversation_id)  # type: ignore[return-value]

    return await _execute_message(conversation_id)


@app.post("/conversations/{conversation_id}/approve", response_model=Conversation)
async def approve_conversation(conversation_id: str) -> Conversation:
    conv = conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.status != ConversationStatus.AWAITING_APPROVAL:
        raise HTTPException(status_code=409, detail="Conversation is not awaiting approval")

    _add_event(conversation_id, "human", "approved", "Human approved the query")
    conversation_store.update(
        conversation_id,
        status=ConversationStatus.ACTIVE,
        approval_id=None,
        review_verdict=None,
        review_recommended_reject=False,
        pending_query=None,
    )
    return await _execute_message(conversation_id)


@app.post("/conversations/{conversation_id}/reject", response_model=Conversation)
def reject_conversation(conversation_id: str) -> Conversation:
    conv = conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.status != ConversationStatus.AWAITING_APPROVAL:
        raise HTTPException(status_code=409, detail="Conversation is not awaiting approval")

    _add_event(conversation_id, "human", "rejected", "Human rejected the query")
    conversation_store.add_message(
        conversation_id, Message(role="agent", content="Query rejected by user.")
    )
    conversation_store.update(
        conversation_id,
        status=ConversationStatus.ACTIVE,
        approval_id=None,
        review_verdict=None,
        review_recommended_reject=False,
        pending_query=None,
    )
    return conversation_store.get(conversation_id)  # type: ignore[return-value]


@app.get("/", include_in_schema=False)
def serve_frontend():
    index = _FRONTEND_DIR / "index.html"
    if index.is_file():
        return FileResponse(str(index), media_type="text/html")
    return JSONResponse({"detail": "Frontend not found"}, status_code=404)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_server_error",
            detail="An unexpected error occurred.",
        ).model_dump(),
    )


def serve():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logger.info(
        "Starting Orchestrator Agent on port %d (mode=%s)",
        settings.orchestrator_port,
        settings.database_mode,
    )
    if settings.database_mode == "a2a":
        try:
            agents_config = _load_agents_config()
            for cfg in agents_config:
                logger.info("  %s -> http://localhost:%d/", cfg["name"], cfg["port"])
        except Exception:
            logger.warning("Could not load agents config for logging")
    uvicorn.run(app, host="0.0.0.0", port=settings.orchestrator_port)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    serve()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_orchestrator.py -v`
Expected: All 27 tests PASS

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `pytest tests/ -v --ignore=tests/e2e`
Expected: All tests PASS (unit tests for MCP client, MCP agent, common module, schemas, store, and orchestrator)

- [ ] **Step 6: Commit**

```bash
git add agents/orchestrator_agent.py tests/test_orchestrator.py
git commit -m "feat: rewrite orchestrator with conversation endpoints and agent isolation"
```

---

### Task 5: PostgresConversationStore

**Files:**
- Modify: `db/repository.py`

- [ ] **Step 1: Rewrite PostgresStore as PostgresConversationStore**

```python
# db/repository.py
"""PostgreSQL-backed conversation store.

Uses psycopg2 for synchronous access. Connection parameters come from the
DATABASE_URL environment variable (standard ``postgres://...`` connection string).

The ``PostgresConversationStore`` class implements the same ``ConversationStore``
protocol as ``InMemoryConversationStore``, making it a drop-in replacement.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

import psycopg2
import psycopg2.extras

from common.schemas import ActivityEvent, Conversation, ConversationStatus, Message

_COLUMNS = (
    "id, title, status, approval_id, review_verdict, review_recommended_reject,"
    " pending_query, messages, events, created_at, updated_at"
)

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS conversations (
    id                         TEXT PRIMARY KEY,
    title                      TEXT NOT NULL DEFAULT '',
    status                     TEXT NOT NULL DEFAULT 'active',
    approval_id                TEXT,
    review_verdict             TEXT,
    review_recommended_reject  BOOLEAN NOT NULL DEFAULT FALSE,
    pending_query              TEXT,
    messages                   JSONB NOT NULL DEFAULT '[]'::jsonb,
    events                     JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL
);
"""

_INSERT = f"""\
INSERT INTO conversations ({_COLUMNS})
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def _get_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL environment variable is required for PostgresConversationStore")
    return psycopg2.connect(url)


def _dict_cursor():
    return {"cursor_factory": psycopg2.extras.RealDictCursor}


def _row_to_conversation(row: dict) -> Conversation:
    messages = [Message(**m) for m in (row.get("messages") or [])]
    events = [ActivityEvent(**e) for e in (row.get("events") or [])]
    return Conversation(
        id=row["id"],
        title=row["title"],
        status=ConversationStatus(row["status"]),
        approval_id=row.get("approval_id"),
        review_verdict=row.get("review_verdict"),
        review_recommended_reject=row.get("review_recommended_reject", False),
        pending_query=row.get("pending_query"),
        messages=messages,
        events=events,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class PostgresConversationStore:
    """PostgreSQL implementation of :class:`store.ConversationStore`."""

    def __init__(self) -> None:
        with _get_conn() as conn, conn.cursor() as cur:
            cur.execute(_CREATE_TABLE)
            conn.commit()

    def create(self, conversation: Conversation) -> None:
        with _get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                _INSERT,
                (
                    conversation.id,
                    conversation.title,
                    conversation.status.value,
                    conversation.approval_id,
                    conversation.review_verdict,
                    conversation.review_recommended_reject,
                    conversation.pending_query,
                    json.dumps([m.model_dump() for m in conversation.messages]),
                    json.dumps([e.model_dump() for e in conversation.events]),
                    conversation.created_at,
                    conversation.updated_at,
                ),
            )
            conn.commit()

    def get(self, conversation_id: str) -> Conversation | None:
        with _get_conn() as conn, conn.cursor(**_dict_cursor()) as cur:
            cur.execute("SELECT * FROM conversations WHERE id = %s", (conversation_id,))
            row = cur.fetchone()
        return _row_to_conversation(row) if row else None

    def list_all(self) -> list[Conversation]:
        with _get_conn() as conn, conn.cursor(**_dict_cursor()) as cur:
            cur.execute("SELECT * FROM conversations ORDER BY updated_at DESC")
            rows = cur.fetchall()
        return [_row_to_conversation(r) for r in rows]

    def add_message(self, conversation_id: str, message: Message) -> None:
        now = datetime.now(UTC).isoformat()
        with _get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE conversations
                   SET messages = messages || %s::jsonb,
                       updated_at = %s
                   WHERE id = %s""",
                (json.dumps([message.model_dump()]), now, conversation_id),
            )
            conn.commit()

    def add_event(self, conversation_id: str, event: ActivityEvent) -> None:
        with _get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE conversations
                   SET events = events || %s::jsonb
                   WHERE id = %s""",
                (json.dumps([event.model_dump()]), conversation_id),
            )
            conn.commit()

    def update(self, conversation_id: str, **fields: Any) -> Conversation | None:
        if not fields:
            return self.get(conversation_id)

        fields["updated_at"] = datetime.now(UTC).isoformat()

        sets = []
        params: list = []
        for key, value in fields.items():
            if key == "status" and isinstance(value, ConversationStatus):
                value = value.value
            sets.append(f"{key} = %s")
            params.append(value)
        params.append(conversation_id)

        with _get_conn() as conn, conn.cursor(**_dict_cursor()) as cur:
            cur.execute(
                f"UPDATE conversations SET {', '.join(sets)} WHERE id = %s RETURNING *",
                params,
            )
            row = cur.fetchone()
            conn.commit()
        return _row_to_conversation(row) if row else None

    def delete(self, conversation_id: str) -> None:
        with _get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
            conn.commit()
```

- [ ] **Step 2: Commit**

```bash
git add db/repository.py
git commit -m "feat: replace PostgresStore with PostgresConversationStore"
```

---

### Task 6: Frontend

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/style.css`
- Modify: `frontend/app.js`

- [ ] **Step 1: Write index.html**

```html
<!-- frontend/index.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>A2A Orchestrator</title>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body>
  <div class="layout">
    <!-- Sidebar -->
    <aside class="sidebar" id="sidebar">
      <div class="sidebar-header">
        <div class="sidebar-title">
          <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/></svg>
          <h1>A2A Orchestrator</h1>
        </div>
        <button class="new-chat-btn" id="new-chat-btn">+ New Chat</button>
      </div>
      <div class="sidebar-content" id="conversation-list">
        <div class="empty-state">
          <p class="empty-title">No conversations yet</p>
          <p class="empty-sub">Start a new chat to begin</p>
        </div>
      </div>
    </aside>

    <!-- Main -->
    <main class="main">
      <button class="menu-btn" id="menu-btn" aria-label="Toggle sidebar">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
      </button>

      <div class="main-scroll" id="main-scroll">
        <div class="content-area" id="content-area">
          <div class="welcome">
            <svg class="welcome-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/></svg>
            <h2>A2A Orchestrator</h2>
            <p>Start a new chat or select a conversation from the sidebar</p>
          </div>
        </div>
      </div>

      <!-- Input bar -->
      <div class="input-bar">
        <form id="message-form" class="input-form">
          <textarea
            id="message-input"
            placeholder="Type a message..."
            maxlength="2000"
            rows="2"
          ></textarea>
          <button type="submit" id="send-btn" disabled>
            <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            Send
          </button>
        </form>
      </div>

      <!-- Log panel -->
      <div class="log-panel" id="log-panel">
        <div class="log-panel-header">
          <span class="log-panel-title">Live Logs</span>
          <button class="log-toggle" id="log-toggle" aria-label="Toggle logs">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><polyline points="6 9 12 15 18 9"/></svg>
          </button>
        </div>
        <div class="log-panel-body" id="log-body"></div>
      </div>
    </main>
  </div>

  <div class="backdrop" id="backdrop"></div>
  <div class="toast-container" id="toast-container"></div>

  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write style.css**

```css
/* frontend/style.css */

/* ── Reset & Base ─────────────────────────────────────────────────────── */

*,
*::before,
*::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

:root {
  --bg: #f9fafb;
  --white: #ffffff;
  --border: #e5e7eb;
  --text: #111827;
  --text-muted: #6b7280;
  --text-light: #9ca3af;
  --primary: #4f46e5;
  --primary-hover: #4338ca;
  --green: #16a34a;
  --green-bg: #dcfce7;
  --green-text: #166534;
  --yellow: #ca8a04;
  --yellow-bg: #fef9c3;
  --yellow-text: #854d0e;
  --yellow-border: #fde68a;
  --red: #dc2626;
  --red-bg: #fee2e2;
  --red-text: #991b1b;
  --orange-bg: #ffedd5;
  --orange-text: #9a3412;
  --radius: 8px;
  --shadow: 0 1px 3px rgba(0,0,0,.1);
  --font: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
}

body {
  font-family: var(--font);
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
  font-size: 14px;
  height: 100vh;
  overflow: hidden;
}

/* ── Layout ──────────────────────────────────────────────────────────── */

.layout {
  display: flex;
  height: 100vh;
}

/* ── Sidebar ─────────────────────────────────────────────────────────── */

.sidebar {
  width: 320px;
  border-right: 1px solid var(--border);
  background: var(--white);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.sidebar-header {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  border-bottom: 1px solid var(--border);
}

.sidebar-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sidebar-title h1 {
  font-size: 16px;
  font-weight: 600;
}

.sidebar-title .icon {
  width: 20px;
  height: 20px;
  color: var(--primary);
  flex-shrink: 0;
}

.new-chat-btn {
  width: 100%;
  padding: 8px 12px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  background: none;
  color: var(--text-muted);
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background .15s, border-color .15s, color .15s;
}

.new-chat-btn:hover {
  background: var(--bg);
  border-color: var(--primary);
  color: var(--primary);
}

.sidebar-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

/* Conversation list items */
.conv-item {
  display: flex;
  align-items: center;
  width: 100%;
  text-align: left;
  padding: 10px 12px;
  border: none;
  background: none;
  border-radius: var(--radius);
  cursor: pointer;
  font: inherit;
  color: var(--text);
  transition: background .15s;
  gap: 8px;
}

.conv-item:hover {
  background: var(--bg);
}

.conv-item.active {
  background: #eef2ff;
  color: var(--primary);
}

.conv-item-body {
  flex: 1;
  min-width: 0;
}

.conv-item-title {
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv-item-time {
  font-size: 12px;
  color: var(--text-light);
  margin-top: 2px;
}

.conv-item-warning {
  color: var(--yellow);
  flex-shrink: 0;
  font-size: 14px;
}

.conv-item .delete-btn {
  opacity: 0;
  background: none;
  border: none;
  color: var(--text-light);
  cursor: pointer;
  padding: 2px 4px;
  font-size: 14px;
  flex-shrink: 0;
  transition: opacity .15s, color .15s;
}

.conv-item:hover .delete-btn {
  opacity: 1;
}

.conv-item .delete-btn:hover {
  color: var(--red);
}

/* ── Empty state ─────────────────────────────────────────────────────── */

.empty-state {
  text-align: center;
  padding: 48px 16px;
  color: var(--text-light);
}

.empty-title {
  font-weight: 500;
  color: var(--text-muted);
}

.empty-sub {
  font-size: 12px;
  margin-top: 4px;
}

/* ── Main area ───────────────────────────────────────────────────────── */

.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  position: relative;
}

.main-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.content-area {
  max-width: 720px;
  margin: 0 auto;
}

/* Welcome */
.welcome {
  text-align: center;
  padding: 80px 16px;
  color: var(--text-light);
}

.welcome-icon {
  width: 48px;
  height: 48px;
  margin-bottom: 12px;
}

.welcome h2 {
  font-size: 18px;
  color: var(--text-muted);
  font-weight: 500;
}

.welcome p {
  font-size: 14px;
  margin-top: 4px;
}

/* ── Input bar ───────────────────────────────────────────────────────── */

.input-bar {
  border-top: 1px solid var(--border);
  background: var(--white);
  padding: 16px 24px;
}

.input-form {
  display: flex;
  gap: 12px;
  max-width: 720px;
  margin: 0 auto;
}

.input-form textarea {
  flex: 1;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 14px;
  font: inherit;
  font-size: 14px;
  resize: none;
  outline: none;
  transition: border-color .15s;
  background: var(--white);
}

.input-form textarea:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(79, 70, 229, .1);
}

.input-form textarea::placeholder {
  color: var(--text-light);
}

.input-form textarea:disabled {
  background: var(--bg);
  color: var(--text-light);
}

.input-form button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 20px;
  border: none;
  border-radius: var(--radius);
  background: var(--primary);
  color: #fff;
  font: inherit;
  font-weight: 500;
  cursor: pointer;
  transition: background .15s, opacity .15s;
  white-space: nowrap;
}

.input-form button:hover:not(:disabled) {
  background: var(--primary-hover);
}

.input-form button:disabled {
  opacity: .5;
  cursor: not-allowed;
}

.input-form button .icon {
  width: 16px;
  height: 16px;
}

/* ── Chat thread ─────────────────────────────────────────────────────── */

.chat-thread {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.chat-msg {
  max-width: 85%;
  padding: 10px 14px;
  border-radius: var(--radius);
  font-size: 13px;
  line-height: 1.5;
}

.chat-msg-user {
  align-self: flex-end;
  background: #eef2ff;
  color: var(--text);
  border-bottom-right-radius: 2px;
}

.chat-msg-agent {
  align-self: flex-start;
  background: var(--bg);
  color: var(--text);
  border-bottom-left-radius: 2px;
}

.chat-msg-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.chat-msg-user .chat-msg-label {
  text-align: right;
  color: var(--primary);
}

.chat-msg-time {
  font-weight: 400;
  color: var(--text-light);
  margin-left: 6px;
}

.chat-msg-content pre {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--mono);
  font-size: 12px;
  margin: 0;
}

/* ── Approval dialog (inline) ────────────────────────────────────────── */

.approval-box {
  border: 1px solid var(--yellow-border);
  background: #fefce8;
  border-radius: var(--radius);
  padding: 16px;
  margin-top: 12px;
}

.approval-box h3 {
  font-size: 13px;
  font-weight: 600;
  color: var(--yellow-text);
  margin-bottom: 6px;
}

.approval-box p {
  font-size: 13px;
  color: #92400e;
}

.approval-verdict {
  font-size: 12px;
  color: #a16207;
  font-family: var(--mono);
  margin: 8px 0 12px;
}

.approval-actions {
  display: flex;
  gap: 8px;
}

.btn-approve,
.btn-reject {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: none;
  border-radius: 6px;
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  color: #fff;
  cursor: pointer;
  transition: background .15s;
}

.btn-approve { background: var(--green); }
.btn-approve:hover { background: #15803d; }
.btn-reject  { background: var(--red); }
.btn-reject:hover  { background: #b91c1c; }

.approval-box-reject {
  border-color: #fca5a5;
  background: #fef2f2;
}

.approval-box-reject h3 {
  color: var(--red-text);
}

.approval-box-reject p {
  color: var(--red-text);
}

/* ── Activity log ────────────────────────────────────────────────────── */

.activity-log {
  margin-top: 16px;
}

.activity-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  padding: 6px 0;
}

.activity-title {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .05em;
  color: var(--text-muted);
}

.activity-toggle {
  background: none;
  border: none;
  color: var(--text-light);
  cursor: pointer;
  font-size: 11px;
}

.activity-body {
  overflow: hidden;
  transition: max-height .2s ease;
}

.activity-body.collapsed {
  max-height: 0;
}

.activity-list {
  list-style: none;
  border-left: 2px solid var(--border);
  margin-left: 6px;
  padding-left: 16px;
}

.activity-list li {
  position: relative;
  margin-bottom: 10px;
  font-size: 12px;
}

.activity-list li::before {
  content: "";
  position: absolute;
  left: -21px;
  top: 6px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--border);
  border: 2px solid var(--white);
}

.activity-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  color: var(--text-light);
}

.activity-agent {
  font-weight: 500;
}

.agent-orchestrator   { color: var(--primary); }
.agent-safety_reviewer { color: var(--yellow); }
.agent-human          { color: var(--green); }

.activity-detail {
  color: var(--text-muted);
  margin-top: 2px;
}

/* ── Toast ───────────────────────────────────────────────────────────── */

.toast-container {
  position: fixed;
  top: 16px;
  right: 16px;
  z-index: 100;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.toast {
  background: var(--red-bg);
  border: 1px solid #fca5a5;
  color: var(--red-text);
  padding: 10px 16px;
  border-radius: var(--radius);
  font-size: 13px;
  box-shadow: var(--shadow);
  display: flex;
  align-items: center;
  gap: 8px;
  animation: toast-in .2s ease;
}

.toast button {
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  padding: 2px;
  font-size: 16px;
  line-height: 1;
  margin-left: auto;
}

@keyframes toast-in {
  from { opacity: 0; transform: translateY(-8px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ── Spinner ─────────────────────────────────────────────────────────── */

.spinner {
  display: inline-block;
  width: 16px;
  height: 16px;
  border: 2px solid #fff;
  border-right-color: transparent;
  border-radius: 50%;
  animation: spin .6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ── Mobile menu ─────────────────────────────────────────────────────── */

.menu-btn {
  display: none;
  position: fixed;
  top: 10px;
  left: 10px;
  z-index: 60;
  background: var(--white);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px;
  cursor: pointer;
  box-shadow: var(--shadow);
}

.menu-btn svg {
  width: 20px;
  height: 20px;
}

.backdrop {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.2);
  z-index: 40;
}

.backdrop.open {
  display: block;
}

/* ── Responsive ──────────────────────────────────────────────────────── */

@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    inset-y: 0;
    left: 0;
    z-index: 50;
    transform: translateX(-100%);
    transition: transform .2s ease;
  }

  .sidebar.open {
    transform: translateX(0);
  }

  .menu-btn {
    display: block;
  }

  .main-scroll {
    padding: 16px;
    padding-top: 56px;
  }

  .input-bar {
    padding: 12px 16px;
  }
}

/* ── Log panel ───────────────────────────────────────────────────────── */

.log-panel {
  width: 100%;
  max-height: 200px;
  border-top: 1px solid var(--border);
  background: #1e1e2e;
  color: #cdd6f4;
  display: flex;
  flex-direction: column;
  font-family: var(--mono);
  font-size: 11px;
  transition: max-height .2s ease;
}

.log-panel.collapsed {
  max-height: 32px;
  overflow: hidden;
}

.log-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  border-bottom: 1px solid #313244;
  flex-shrink: 0;
}

.log-panel-title {
  font-weight: 600;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .05em;
  color: #a6adc8;
}

.log-toggle {
  background: none;
  border: none;
  color: #a6adc8;
  cursor: pointer;
  padding: 2px;
}

.log-panel.collapsed .log-toggle svg {
  transform: rotate(180deg);
}

.log-panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 4px 12px;
}

.log-line {
  padding: 1px 0;
  white-space: pre-wrap;
  word-break: break-all;
}

.log-INFO    { color: #89b4fa; }
.log-WARNING { color: #f9e2af; }
.log-ERROR   { color: #f38ba8; }
```

- [ ] **Step 3: Write app.js**

```javascript
// frontend/app.js
/**
 * A2A Orchestrator — Frontend Application
 *
 * Vanilla JS client for the conversation-based orchestrator API.
 */

"use strict";

/* ── API Client ──────────────────────────────────────────────────────── */

class ApiClient {
  constructor(baseUrl = "") {
    this.baseUrl = baseUrl;
  }

  async _request(path, options = {}) {
    const res = await fetch(`${this.baseUrl}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed: ${res.status}`);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  createConversation()      { return this._request("/conversations", { method: "POST" }); }
  getConversations()        { return this._request("/conversations"); }
  getConversation(id)       { return this._request(`/conversations/${encodeURIComponent(id)}`); }
  deleteConversation(id)    { return this._request(`/conversations/${encodeURIComponent(id)}`, { method: "DELETE" }); }
  sendMessage(id, content)  { return this._request(`/conversations/${encodeURIComponent(id)}/messages`, { method: "POST", body: JSON.stringify({ content }) }); }
  approve(id)               { return this._request(`/conversations/${encodeURIComponent(id)}/approve`, { method: "POST" }); }
  reject(id)                { return this._request(`/conversations/${encodeURIComponent(id)}/reject`, { method: "POST" }); }
}

const api = new ApiClient();

/* ── State ───────────────────────────────────────────────────────────── */

let conversations = [];
let selectedId = null;
let currentConv = null;
let pollTimer = null;

/* ── DOM refs ────────────────────────────────────────────────────────── */

const $ = (sel) => document.querySelector(sel);
const sidebar       = $("#sidebar");
const backdrop      = $("#backdrop");
const menuBtn       = $("#menu-btn");
const convList      = $("#conversation-list");
const contentArea   = $("#content-area");
const messageForm   = $("#message-form");
const messageInput  = $("#message-input");
const sendBtn       = $("#send-btn");
const toastBox      = $("#toast-container");
const logPanel      = $("#log-panel");
const logToggle     = $("#log-toggle");
const logBody       = $("#log-body");
const newChatBtn    = $("#new-chat-btn");

/* ── Helpers ─────────────────────────────────────────────────────────── */

function fmtTime(iso) {
  try { return new Date(iso).toLocaleTimeString(); }
  catch { return iso; }
}

function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

function showToast(msg) {
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = `<span>${escapeHtml(msg)}</span><button aria-label="Close">&times;</button>`;
  el.querySelector("button").onclick = () => el.remove();
  toastBox.appendChild(el);
  setTimeout(() => el.remove(), 6000);
}

/* ── Render: sidebar conversation list ───────────────────────────────── */

function renderSidebar() {
  if (!conversations.length) {
    convList.innerHTML = `
      <div class="empty-state">
        <p class="empty-title">No conversations yet</p>
        <p class="empty-sub">Start a new chat to begin</p>
      </div>`;
    return;
  }

  convList.innerHTML = conversations.map((c) => `
    <div class="conv-item ${c.id === selectedId ? "active" : ""}" data-id="${escapeHtml(c.id)}">
      <div class="conv-item-body">
        <div class="conv-item-title">${escapeHtml(c.title)}</div>
        <div class="conv-item-time">${fmtTime(c.updated_at)}</div>
      </div>
      ${c.status === "awaiting_approval" ? '<span class="conv-item-warning" title="Awaiting approval">&#9888;</span>' : ""}
      <button class="delete-btn" data-delete="${escapeHtml(c.id)}" title="Delete conversation">&times;</button>
    </div>
  `).join("");

  convList.querySelectorAll(".conv-item").forEach((el) => {
    el.addEventListener("click", (e) => {
      if (e.target.closest(".delete-btn")) return;
      selectConversation(el.dataset.id);
      closeSidebar();
    });
  });

  convList.querySelectorAll(".delete-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id = btn.dataset.delete;
      try {
        await api.deleteConversation(id);
        if (selectedId === id) {
          selectedId = null;
          currentConv = null;
          renderContent();
          updateInput();
        }
        await fetchConversations();
      } catch (err) {
        showToast(err.message);
      }
    });
  });
}

/* ── Render: main content area ───────────────────────────────────────── */

function renderContent() {
  if (!currentConv) {
    contentArea.innerHTML = `
      <div class="welcome">
        <svg class="welcome-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>
        </svg>
        <h2>A2A Orchestrator</h2>
        <p>Start a new chat or select a conversation from the sidebar</p>
      </div>`;
    return;
  }

  const c = currentConv;
  let html = "";

  // Messages
  if (c.messages && c.messages.length) {
    html += `<div class="chat-thread">`;
    for (const msg of c.messages) {
      const isUser = msg.role === "user";
      html += `
        <div class="chat-msg ${isUser ? "chat-msg-user" : "chat-msg-agent"}">
          <div class="chat-msg-label">${isUser ? "You" : "Agent"} <span class="chat-msg-time">${fmtTime(msg.timestamp)}</span></div>
          <div class="chat-msg-content">${isUser ? escapeHtml(msg.content) : "<pre>" + escapeHtml(msg.content) + "</pre>"}</div>
        </div>`;
    }
    html += `</div>`;
  }

  // Approval dialog
  if (c.status === "awaiting_approval" && c.review_verdict) {
    const isReject = c.review_recommended_reject;
    const heading = isReject
      ? "Safety Reviewer Recommends Rejection"
      : "Human Approval Required";
    const desc = isReject
      ? "The safety reviewer recommends rejecting this query. You may override this decision."
      : "The safety reviewer approved this destructive query, but it requires your confirmation before execution.";
    html += `
      <div class="approval-box${isReject ? " approval-box-reject" : ""}">
        <h3>${heading}</h3>
        <p>${desc}</p>
        <div class="approval-verdict">${escapeHtml(c.review_verdict)}</div>
        <div class="approval-actions">
          <button class="btn-approve" data-action="approve">&#10003; Approve &amp; Execute</button>
          <button class="btn-reject" data-action="reject">&#10007; Reject</button>
        </div>
      </div>`;
  }

  // Activity log
  if (c.events && c.events.length) {
    html += `
      <div class="activity-log">
        <div class="activity-header" id="activity-toggle">
          <span class="activity-title">Agent Activity (${c.events.length})</span>
          <button class="activity-toggle">Show</button>
        </div>
        <div class="activity-body collapsed" id="activity-body">
          <ul class="activity-list">
            ${c.events.map((e) => `
              <li>
                <div class="activity-meta">
                  <span>${fmtTime(e.timestamp)}</span>
                  <span class="activity-agent agent-${e.agent}">${escapeHtml(e.agent)}</span>
                  <span>${escapeHtml(e.action)}</span>
                </div>
                ${e.detail ? `<div class="activity-detail">${escapeHtml(e.detail)}</div>` : ""}
              </li>
            `).join("")}
          </ul>
        </div>
      </div>`;
  }

  contentArea.innerHTML = html;

  // Wire approval buttons
  contentArea.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const action = btn.dataset.action;
      try {
        if (action === "approve") currentConv = await api.approve(c.id);
        else                      currentConv = await api.reject(c.id);
        renderContent();
        updateInput();
        await fetchConversations();
      } catch (err) {
        showToast(err.message);
      }
    });
  });

  // Wire activity toggle
  const actToggle = $("#activity-toggle");
  if (actToggle) {
    actToggle.addEventListener("click", () => {
      const body = $("#activity-body");
      const btn = actToggle.querySelector(".activity-toggle");
      body.classList.toggle("collapsed");
      btn.textContent = body.classList.contains("collapsed") ? "Show" : "Hide";
    });
  }

  // Auto-scroll to bottom
  const mainScroll = $("#main-scroll");
  mainScroll.scrollTop = mainScroll.scrollHeight;
}

/* ── Input state ─────────────────────────────────────────────────────── */

function updateInput() {
  const awaiting = currentConv && currentConv.status === "awaiting_approval";
  messageInput.disabled = awaiting || !selectedId;
  sendBtn.disabled = awaiting || !selectedId || !messageInput.value.trim();
  if (awaiting) {
    messageInput.placeholder = "Awaiting approval...";
  } else if (!selectedId) {
    messageInput.placeholder = "Start a new chat to begin...";
  } else {
    messageInput.placeholder = "Type a message...";
  }
}

/* ── Data fetching ───────────────────────────────────────────────────── */

async function fetchConversations() {
  try {
    conversations = await api.getConversations();
    renderSidebar();
  } catch (err) {
    console.error("Failed to fetch conversations:", err);
  }
}

async function fetchConversation(id) {
  try {
    currentConv = await api.getConversation(id);
    renderContent();
    updateInput();
  } catch (err) {
    console.error("Failed to fetch conversation:", err);
  }
}

async function selectConversation(id) {
  selectedId = id;
  renderSidebar();
  await fetchConversation(id);
}

function startPoll() {
  stopPoll();
  pollTimer = setInterval(async () => {
    if (selectedId) await fetchConversation(selectedId);
  }, 3000);
}

function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

/* ── Mobile sidebar ──────────────────────────────────────────────────── */

function openSidebar()  { sidebar.classList.add("open"); backdrop.classList.add("open"); }
function closeSidebar() { sidebar.classList.remove("open"); backdrop.classList.remove("open"); }

menuBtn.addEventListener("click", () => {
  sidebar.classList.contains("open") ? closeSidebar() : openSidebar();
});
backdrop.addEventListener("click", closeSidebar);

/* ── New chat ────────────────────────────────────────────────────────── */

newChatBtn.addEventListener("click", async () => {
  try {
    const conv = await api.createConversation();
    selectedId = conv.id;
    currentConv = conv;
    await fetchConversations();
    renderContent();
    updateInput();
    messageInput.focus();
    closeSidebar();
  } catch (err) {
    showToast(err.message);
  }
});

/* ── Form handling ───────────────────────────────────────────────────── */

messageInput.addEventListener("input", () => {
  sendBtn.disabled = !messageInput.value.trim() || !selectedId;
});

messageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    messageForm.requestSubmit();
  }
});

messageForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = messageInput.value.trim();
  if (!text || !selectedId) return;

  sendBtn.disabled = true;
  sendBtn.innerHTML = '<span class="spinner"></span> Sending...';

  try {
    currentConv = await api.sendMessage(selectedId, text);
    messageInput.value = "";
    renderContent();
    updateInput();
    await fetchConversations();
  } catch (err) {
    showToast(err.message);
  } finally {
    sendBtn.disabled = !messageInput.value.trim() || !selectedId;
    sendBtn.innerHTML = `
      <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
      </svg> Send`;
  }
});

/* ── Init ────────────────────────────────────────────────────────────── */

fetchConversations();
updateInput();

/* ── SSE Log Stream ──────────────────────────────────────────────────── */

function connectLogStream() {
  const evtSource = new EventSource("/logs/stream");
  evtSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      const line = document.createElement("div");
      line.className = `log-line log-${data.level}`;
      line.textContent = `[${data.level}] ${data.logger}: ${data.message}`;
      logBody.appendChild(line);
      while (logBody.children.length > 200) logBody.removeChild(logBody.firstChild);
      logBody.scrollTop = logBody.scrollHeight;
    } catch { /* ignore malformed */ }
  };
  evtSource.onerror = () => {
    evtSource.close();
    setTimeout(connectLogStream, 3000);
  };
}

if (logToggle) {
  logToggle.addEventListener("click", () => {
    logPanel.classList.toggle("collapsed");
  });
}

connectLogStream();
```

- [ ] **Step 4: Manual test**

Run: `python -m agents.orchestrator_agent`

Open `http://localhost:8000` in a browser. Verify:
1. "New Chat" button creates a conversation in the sidebar
2. Typing a message and pressing Enter sends it, shows user + agent messages
3. Starting a second chat shows separate message threads
4. Destructive query ("delete employee 5") shows inline approval dialog
5. Approve/Reject buttons work
6. Delete button removes conversation from sidebar
7. Live logs panel shows at the bottom

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html frontend/style.css frontend/app.js
git commit -m "feat: ChatGPT-style conversation UI with new chat and inline approval"
```

---

### Task 7: E2E Tests, Lint & Cleanup

**Files:**
- Modify: `tests/e2e/test_e2e_stub.py`

- [ ] **Step 1: Update E2E test stubs**

```python
# tests/e2e/test_e2e_stub.py
"""End-to-end tests — orchestrator → specialist agent round-trip.

These tests require live infrastructure (MCP server, Gemini API key) and are
skipped by default unless the E2E_TESTS environment variable is set.

Usage:
    E2E_TESTS=1 pytest tests/e2e/ -v

Pre-requisites:
    1. Start all services:  python run_system.py
    2. Set required env vars in .env
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("E2E_TESTS"),
    reason="Set E2E_TESTS=1 to run end-to-end tests (requires live infra)",
)


@pytest.mark.asyncio
async def test_orchestrator_health():
    """Orchestrator /health should return 200."""
    import httpx

    orchestrator_url = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8000")
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{orchestrator_url}/health", timeout=10)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_db_agent_card_reachable():
    """Database Reader AgentCard should be reachable."""
    import httpx

    db_agent_url = os.environ.get("DB_READER_URL", "http://localhost:8001/")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{db_agent_url.rstrip('/')}/.well-known/agent-card.json",
            timeout=10,
        )
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "Database Reader"


@pytest.mark.asyncio
async def test_graph_agent_card_reachable():
    """Graph Agent AgentCard should be reachable from orchestrator."""
    import httpx

    graph_agent_url = os.environ.get("GRAPH_AGENT_URL", "http://localhost:8002/")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{graph_agent_url.rstrip('/')}/.well-known/agent-card.json",
            timeout=10,
        )
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "Graph Agent"


@pytest.mark.asyncio
async def test_full_conversation_round_trip():
    """Full round-trip: create conversation → send message → get response."""
    import httpx

    orchestrator_url = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8000")
    async with httpx.AsyncClient() as client:
        # Create conversation
        create_resp = await client.post(
            f"{orchestrator_url}/conversations",
            timeout=10,
        )
        assert create_resp.status_code == 201
        conv_id = create_resp.json()["id"]

        # Send message
        msg_resp = await client.post(
            f"{orchestrator_url}/conversations/{conv_id}/messages",
            json={"content": "List all tables in the database"},
            timeout=120,
        )
        assert msg_resp.status_code == 200
        data = msg_resp.json()
        assert data["status"] == "active"
        assert len(data["messages"]) >= 2
```

- [ ] **Step 2: Run the full test suite**

Run: `pytest tests/ -v --ignore=tests/e2e`
Expected: All tests PASS

- [ ] **Step 3: Run lint and format**

Run: `ruff check . && ruff format --check .`
Expected: No errors. If there are lint issues, fix them:
Run: `ruff check --fix . && ruff format .`

- [ ] **Step 4: Run type checking**

Run: `mypy agents/ tools/ mcp_client/ common/ db/`
Expected: No errors (or only pre-existing ones unrelated to this change)

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/test_e2e_stub.py
git commit -m "test: update e2e stubs for conversation API"
```
