"""Integration tests for A2A server request handling.

Starts a generic MCP agent FastAPI app via ASGI transport (no real port) and
sends A2A protocol messages to verify the server handles them correctly.

Run:
    pytest tests/integration/test_a2a_server.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest


@pytest.fixture()
def mock_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("AGENT_API_KEY", "")


@pytest.fixture()
def a2a_app(mock_env):
    """Build a minimal A2AServer FastAPI app for integration testing."""
    mock_model = MagicMock()
    mock_client = MagicMock()

    with (
        patch("agents.model.create_model", return_value=mock_model),
        patch("mcp_client.client.get_mcp_client", return_value=mock_client),
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
            "description": "Test database agent",
            "system_prompt": "You are a test agent.",
        }
        agent = create_mcp_agent(agent_config)
        server = A2AServer(
            agent=agent,
            http_url="http://127.0.0.1:9001/",
            version="1.0.0",
            skills=[
                AgentSkill(
                    id="test-skill",
                    name="Test Skill",
                    description="A test skill",
                    tags=["test"],
                )
            ],
            task_store=InMemoryA2ATaskStore(),
        )
        return server.to_fastapi_app()


@pytest.mark.asyncio
async def test_agent_card_accessible(a2a_app):
    """AgentCard endpoint must respond 200 without auth."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=a2a_app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/.well-known/agent-card.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "Test Agent"


@pytest.mark.asyncio
async def test_send_message_invalid_body_returns_jsonrpc_error(a2a_app):
    """POST / with invalid JSON should return a JSON-RPC parse error."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=a2a_app),
        base_url="http://test",
    ) as client:
        resp = await client.post("/", content=b"not-json")
    assert resp.status_code == 200
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == -32700


@pytest.mark.asyncio
async def test_auth_middleware_blocks_without_key():
    """When AGENT_API_KEY is set, requests without the header are rejected."""
    mock_model = MagicMock()
    mock_client = MagicMock()

    with (
        patch("agents.model.create_model", return_value=mock_model),
        patch("mcp_client.client.get_mcp_client", return_value=mock_client),
    ):
        from a2a.types import AgentSkill
        from strands.multiagent.a2a import A2AServer

        from agents.mcp_agent import create_mcp_agent
        from common.auth import AgentAuthMiddleware
        from common.task_store import InMemoryA2ATaskStore

        agent = create_mcp_agent(
            {
                "name": "Auth Test Agent",
                "mcp_url": "https://example.com/mcp",
                "description": "Auth test agent",
            }
        )
        server = A2AServer(
            agent=agent,
            http_url="http://127.0.0.1:9001/",
            version="1.0.0",
            skills=[AgentSkill(id="t", name="T", description="t", tags=["t"])],
            task_store=InMemoryA2ATaskStore(),
        )
        app = server.to_fastapi_app()
        app.add_middleware(AgentAuthMiddleware, api_key="secret-key")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.post("/", json={})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_middleware_allows_agent_card_without_key():
    """AgentCard endpoint must be accessible even when auth is enabled."""
    mock_model = MagicMock()
    mock_client = MagicMock()

    with (
        patch("agents.model.create_model", return_value=mock_model),
        patch("mcp_client.client.get_mcp_client", return_value=mock_client),
    ):
        from a2a.types import AgentSkill
        from strands.multiagent.a2a import A2AServer

        from agents.mcp_agent import create_mcp_agent
        from common.auth import AgentAuthMiddleware
        from common.task_store import InMemoryA2ATaskStore

        agent = create_mcp_agent(
            {
                "name": "Auth Card Test",
                "mcp_url": "https://example.com/mcp",
                "description": "Auth card test agent",
            }
        )
        server = A2AServer(
            agent=agent,
            http_url="http://127.0.0.1:9001/",
            version="1.0.0",
            skills=[AgentSkill(id="t", name="T", description="t", tags=["t"])],
            task_store=InMemoryA2ATaskStore(),
        )
        app = server.to_fastapi_app()
        app.add_middleware(AgentAuthMiddleware, api_key="secret-key")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/.well-known/agent-card.json")
    assert resp.status_code == 200
