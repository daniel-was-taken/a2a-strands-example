"""Unit tests for the common/ module (config, auth, task_store, logging)."""

from __future__ import annotations

import json
import logging
import threading

import pytest

# ── common.task_store ─────────────────────────────────────────────────────────


class TestInMemoryA2ATaskStore:
    def _make_task(self, task_id: str):
        from a2a.types import Task, TaskState, TaskStatus

        return Task(
            id=task_id,
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.submitted),
        )

    def test_save_and_get(self):
        from common.task_store import InMemoryA2ATaskStore

        store = InMemoryA2ATaskStore()
        task = self._make_task("t1")
        store.save(task)
        assert store.get("t1") is not None
        assert store.get("t1").id == "t1"

    def test_get_missing_returns_none(self):
        from common.task_store import InMemoryA2ATaskStore

        store = InMemoryA2ATaskStore()
        assert store.get("nonexistent") is None

    def test_delete_removes_task(self):
        from common.task_store import InMemoryA2ATaskStore

        store = InMemoryA2ATaskStore()
        task = self._make_task("t2")
        store.save(task)
        store.delete("t2")
        assert store.get("t2") is None

    def test_delete_nonexistent_does_not_raise(self):
        from common.task_store import InMemoryA2ATaskStore

        store = InMemoryA2ATaskStore()
        store.delete("nonexistent")  # Should not raise

    def test_thread_safety(self):
        """Concurrent saves from multiple threads must not corrupt state."""
        from common.task_store import InMemoryA2ATaskStore

        store = InMemoryA2ATaskStore()
        errors: list[Exception] = []

        def _save_many(prefix: str) -> None:
            try:
                for i in range(50):
                    task = self._make_task(f"{prefix}-{i}")
                    store.save(task)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_save_many, args=(f"t{n}",)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread-safety errors: {errors}"
        assert len(store._tasks) == 200  # 4 threads × 50 tasks


# ── common.logging_setup ──────────────────────────────────────────────────────


class TestStructuredJsonFormatter:
    def test_output_is_valid_json(self):
        from common.logging_setup import StructuredJsonFormatter

        formatter = StructuredJsonFormatter(agent_name="test-agent")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello world",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "hello world"
        assert parsed["level"] == "INFO"
        assert parsed["agent_name"] == "test-agent"

    def test_empty_fields_omitted(self):
        from common.logging_setup import StructuredJsonFormatter

        formatter = StructuredJsonFormatter(agent_name="")
        record = logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg="msg",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        # agent_name="" and session_id="" should be omitted
        assert "agent_name" not in parsed
        assert "session_id" not in parsed

    def test_extra_fields_included(self):
        from common.logging_setup import StructuredJsonFormatter

        formatter = StructuredJsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="msg",
            args=(),
            exc_info=None,
        )
        record.task_id = "task-123"
        record.session_id = "sess-456"
        record.duration_ms = 42
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["task_id"] == "task-123"
        assert parsed["session_id"] == "sess-456"
        assert parsed["duration_ms"] == 42


# ── common.auth ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auth_middleware_passthrough_when_no_key():
    """Auth middleware must be a no-op when api_key is empty."""
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from common.auth import AgentAuthMiddleware

    def homepage(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(AgentAuthMiddleware, api_key="")

    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_auth_middleware_rejects_missing_key():
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from common.auth import AgentAuthMiddleware

    def homepage(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(AgentAuthMiddleware, api_key="secret")

    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_middleware_accepts_correct_key():
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from common.auth import AgentAuthMiddleware

    def homepage(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(AgentAuthMiddleware, api_key="secret")

    client = TestClient(app)
    resp = client.get("/", headers={"x-agent-api-key": "secret"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_auth_middleware_exempts_agent_card():
    """/.well-known/agent-card.json must bypass auth."""
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from common.auth import AgentAuthMiddleware

    def card(request):
        return PlainTextResponse("{}")

    app = Starlette(routes=[Route("/.well-known/agent-card.json", card)])
    app.add_middleware(AgentAuthMiddleware, api_key="secret")

    client = TestClient(app)
    resp = client.get("/.well-known/agent-card.json")
    assert resp.status_code == 200
