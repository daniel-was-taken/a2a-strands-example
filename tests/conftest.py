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
            "name": "Database Agent",
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
        {
            "name": "BRD Specialist",
            "type": "custom",
            "port": 9002,
            "description": "Test BRD specialist",
            "module": "agents.brd_specialist",
            "factory": "create_agent",
            "skills": [],
        },
        {
            "name": "Graph Reviewer",
            "type": "custom",
            "port": 9003,
            "description": "Test graph reviewer",
            "module": "agents.graph_reviewer",
            "factory": "create_agent",
            "skills": [],
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
    from core.store import conversation_store

    conversation_store._conversations.clear()


@pytest.fixture(autouse=True)
def _reset_agent():
    """Reset the lazy-loaded agent singleton between tests."""
    import core.orchestrator as orch

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
        patch("core.model.create_model", return_value=mock_model),
        patch("core.server.create_mcp_agent", return_value=mock_agent),
        patch(
            "core.orchestrator.create_safety_reviewer",
            return_value=mock_agent,
        ),
        patch(
            "core.orchestrator.review_delete_request",
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
    from core.orchestrator import app

    yield TestClient(app)


@pytest.fixture()
def client_approve(mock_agents_approve):
    """TestClient with fully mocked backend (safety reviewer approves)."""
    from core.orchestrator import app

    yield TestClient(app)
