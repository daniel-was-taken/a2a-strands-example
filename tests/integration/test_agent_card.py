"""Integration + contract tests for A2A AgentCard endpoints.

These tests build the FastAPI app from a generic MCP agent and validate
the AgentCard JSON schema without needing a real LLM or database.

Run:
    pytest tests/integration/ -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest


@pytest.fixture()
def mock_env(monkeypatch):
    """Minimal env vars required to import agent modules."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("AGENT_API_KEY", "")


@pytest.fixture()
def agent_app(mock_env):
    """Build a generic MCP agent FastAPI app with all external calls mocked."""
    mock_model = MagicMock()
    mock_mcp = MagicMock()

    with (
        patch("agents.model.create_model", return_value=mock_model),
        patch("mcp_client.client.get_mcp_client", return_value=mock_mcp),
        patch("common.logging_setup.configure_logging"),
        patch("common.tracing.configure_tracing"),
    ):
        from a2a.types import AgentSkill
        from strands.multiagent.a2a import A2AServer

        from agents.mcp_agent import create_mcp_agent
        from common.task_store import InMemoryA2ATaskStore

        agent_config = {
            "name": "Test Agent",
            "mcp_url": "https://example.com/mcp",
            "description": "A test agent for integration tests",
            "system_prompt": "You are a test agent.",
        }
        skills = [
            AgentSkill(
                id="test-skill",
                name="Test Skill",
                description="A test skill for integration tests",
                tags=["test"],
            ),
        ]
        agent = create_mcp_agent(agent_config)
        server = A2AServer(
            agent=agent,
            http_url="http://127.0.0.1:9001/",
            version="1.0.0",
            skills=skills,
            task_store=InMemoryA2ATaskStore(),
        )
        return server.to_fastapi_app()


@pytest.mark.asyncio
async def test_agent_card_endpoint_returns_200(agent_app):
    """AgentCard must be served at /.well-known/agent-card.json."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=agent_app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/.well-known/agent-card.json")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_agent_card_is_valid_json(agent_app):
    """AgentCard response must be parseable JSON."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=agent_app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/.well-known/agent-card.json")
    data = resp.json()
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_agent_card_required_fields(agent_app):
    """AgentCard must contain the required A2A spec fields."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=agent_app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/.well-known/agent-card.json")
    card = resp.json()

    required_fields = {"name", "description", "version", "url", "capabilities", "skills"}
    missing = required_fields - set(card.keys())
    assert not missing, f"AgentCard missing required fields: {missing}"


@pytest.mark.asyncio
async def test_agent_card_skills_populated(agent_app):
    """AgentCard skills list must be non-empty and well-formed."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=agent_app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/.well-known/agent-card.json")
    card = resp.json()

    skills = card.get("skills", [])
    assert len(skills) >= 1, "AgentCard must advertise at least one skill"
    for skill in skills:
        assert "id" in skill, "Each skill must have an id"
        assert "name" in skill, "Each skill must have a name"
        assert "description" in skill, "Each skill must have a description"
        assert "tags" in skill, "Each skill must have tags"


@pytest.mark.asyncio
async def test_agent_card_version_is_semver(agent_app):
    """AgentCard version should follow semver (major.minor.patch)."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=agent_app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/.well-known/agent-card.json")
    card = resp.json()
    version = card.get("version", "")
    parts = version.split(".")
    assert len(parts) == 3, f"Version '{version}' is not semver (expected major.minor.patch)"
    assert all(p.isdigit() for p in parts), f"Version parts must be integers: {parts}"
