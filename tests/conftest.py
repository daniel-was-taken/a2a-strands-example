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


@pytest.fixture()
def mock_agents():
    """Patch Agent and A2AClientToolProvider so no real LLM or A2A calls are made."""
    mock_agent = MagicMock()
    mock_agent.return_value = "Test agent response"

    mock_model = MagicMock()

    mock_provider = MagicMock()
    mock_provider.tools = []

    with (
        patch("agents.model.create_model", return_value=mock_model),
        patch(
            "agents.orchestrator_agent.create_model", return_value=mock_model
        ),
        patch("agents.orchestrator_agent.Agent", return_value=mock_agent),
        patch(
            "agents.orchestrator_agent.A2AClientToolProvider",
            return_value=mock_provider,
        ),
        patch(
            "agents.orchestrator_agent.create_safety_reviewer",
            return_value=mock_agent,
        ),
        patch(
            "agents.orchestrator_agent.review_delete_request",
            return_value=(False, "REJECT: test rejection"),
        ),
    ):
        yield mock_agent


@pytest.fixture()
def client(mock_agents):
    """TestClient with fully mocked backend."""
    from agents.orchestrator_agent import app

    yield TestClient(app)
