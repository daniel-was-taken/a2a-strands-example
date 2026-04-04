"""Tests for the generic MCP agent factory and MCP client."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


# ── MCP Agent Factory ────────────────────────────────────────────────────────


def test_create_mcp_agent_returns_agent():
    """create_mcp_agent should return a Strands Agent with correct config."""
    mock_client = MagicMock()
    mock_model = MagicMock()

    config = {
        "name": "Test Agent",
        "mcp_url": "https://example.com/mcp",
        "description": "A test agent",
        "system_prompt": "You are a test agent.",
    }

    with (
        patch("core.server.create_mcp_client", return_value=mock_client),
        patch("core.server.create_model", return_value=mock_model),
        patch("core.server.Agent") as mock_agent_cls,
    ):
        from core.server import create_mcp_agent

        create_mcp_agent(config)

        mock_agent_cls.assert_called_once_with(
            model=mock_model,
            name="Test Agent",
            description="A test agent",
            system_prompt="You are a test agent.",
            tools=[mock_client],
            callback_handler=None,
        )


def test_create_mcp_agent_passes_auth():
    """create_mcp_agent should forward auth config to create_mcp_client."""
    mock_client = MagicMock()

    config = {
        "name": "Auth Agent",
        "mcp_url": "https://example.com/mcp",
        "auth": {"type": "bearer", "env_var": "MY_TOKEN"},
    }

    with (
        patch("core.server.create_mcp_client", return_value=mock_client) as mock_get,
        patch("core.server.create_model", return_value=MagicMock()),
        patch("core.server.Agent"),
    ):
        from core.server import create_mcp_agent

        create_mcp_agent(config)

        mock_get.assert_called_once_with(
            mcp_url="https://example.com/mcp",
            auth={"type": "bearer", "env_var": "MY_TOKEN"},
        )


def test_create_mcp_agent_default_system_prompt():
    """create_mcp_agent should use default system prompt when none provided."""
    config = {
        "name": "Minimal Agent",
        "mcp_url": "https://example.com/mcp",
    }

    with (
        patch("core.server.create_mcp_client", return_value=MagicMock()),
        patch("core.server.create_model", return_value=MagicMock()),
        patch("core.server.Agent") as mock_agent_cls,
    ):
        from core.server import create_mcp_agent

        create_mcp_agent(config)

        call_kwargs = mock_agent_cls.call_args[1]
        assert call_kwargs["system_prompt"] == "Use the available tools."


def test_load_agents_config_reads_yaml(tmp_path):
    """load_agents_config should parse agents.yaml and return the agents list."""
    import yaml

    config = {
        "agents": [
            {
                "name": "A1",
                "type": "mcp",
                "port": 9001,
                "mcp_url": "https://example.com/mcp",
                "tools": [],
                "skills": [],
            },
        ]
    }
    config_path = tmp_path / "agents.yaml"
    config_path.write_text(yaml.dump(config))

    from core.server import load_agents_config

    agents = load_agents_config(str(config_path))
    assert len(agents) == 1
    assert agents[0]["name"] == "A1"


# ── MCP Client ───────────────────────────────────────────────────────────────


def test_create_mcp_client_no_auth():
    """create_mcp_client without auth should create client with no auth headers."""
    with patch("core.mcp.streamable_http_client"):
        from core.mcp import create_mcp_client

        client = create_mcp_client("https://example.com/mcp")
        assert client is not None


def test_create_mcp_client_bearer_auth(monkeypatch):
    """create_mcp_client with bearer auth should read token from env."""
    monkeypatch.setenv("MY_TOKEN", "secret-123")
    with patch("core.mcp.streamable_http_client"):
        from core.mcp import create_mcp_client

        client = create_mcp_client(
            "https://example.com/mcp",
            auth={"type": "bearer", "env_var": "MY_TOKEN"},
        )
        assert client is not None


def test_create_mcp_client_bearer_auth_missing_env():
    """create_mcp_client with bearer auth should raise when env var is missing."""
    os.environ.pop("MISSING_TOKEN", None)

    with patch("core.mcp.streamable_http_client"):
        from core.mcp import create_mcp_client

        with pytest.raises(KeyError):
            create_mcp_client(
                "https://example.com/mcp",
                auth={"type": "bearer", "env_var": "MISSING_TOKEN"},
            )


def test_create_mcp_client_returns_reconnecting_subclass():
    """create_mcp_client should return a ReconnectingMCPClient."""
    with patch("core.mcp.streamable_http_client"):
        from core.mcp import ReconnectingMCPClient, create_mcp_client

        client = create_mcp_client("https://example.com/mcp")
        assert isinstance(client, ReconnectingMCPClient)


def test_reconnecting_client_calls_stop_and_start_on_dead_session():
    """ReconnectingMCPClient should stop+start when session is dead."""
    with patch("core.mcp.streamable_http_client"):
        from core.mcp import create_mcp_client

        client = create_mcp_client("https://example.com/mcp")

        # Simulate a dead session
        client._background_thread = MagicMock()
        client._background_thread.is_alive.return_value = False
        client._close_future = MagicMock()
        client._close_future.done.return_value = True

        # Patch stop and start to prevent actual connection attempts
        client.stop = MagicMock()
        client.start = MagicMock()

        client._reconnect()

        client.stop.assert_called_once_with(None, None, None)
        client.start.assert_called_once()
