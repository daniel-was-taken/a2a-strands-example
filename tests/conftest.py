"""Configuration and fixtures for tests.

Run:  pytest tests/ -v
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch):
    """Ensure required env vars are set for tests."""
    monkeypatch.setenv("NEON_API_KEY", "test-key")
    monkeypatch.setenv("NEON_PROJECT_ID", "test-project")
    monkeypatch.setenv("NEON_DATABASE", "test-db")
    monkeypatch.setenv("NEON_BRANCH_ID", "main")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("DATABASE_AGENT_URL", "http://localhost:8001/")
    monkeypatch.setenv("DATABASE_MODE", "direct")


@pytest.fixture(autouse=True)
def _clear_store():
    """Reset the in-memory store between tests."""
    from store import query_store

    query_store._records.clear()


@pytest.fixture(autouse=True)
def _reset_agent():
    """Reset the lazy-loaded agent singleton between tests."""
    import agents.orchestrator_agent as orch

    orch._agent = None
    yield
    orch._agent = None


def _make_mock_agents(review_return):
    """Shared helper to build mock patches with a given review_delete_request return."""
    mock_agent = MagicMock()
    mock_agent.return_value = "Test agent response"

    mock_model = MagicMock()

    return (
        mock_agent,
        patch("agents.model.create_model", return_value=mock_model),
        patch("agents.db_agent.create_database_agent", return_value=mock_agent),
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
    mock_agent, *patches = _make_mock_agents(
        (True, "APPROVE: clearly scoped request")
    )
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
