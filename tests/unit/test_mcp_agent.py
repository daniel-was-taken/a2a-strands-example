"""Tests for the generic MCP agent factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


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
        patch("agents.mcp_agent.create_mcp_client", return_value=mock_client),
        patch("agents.mcp_agent.create_model", return_value=mock_model),
        patch("agents.mcp_agent.Agent") as mock_agent_cls,
    ):
        from agents.mcp_agent import create_mcp_agent

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
        patch("agents.mcp_agent.create_mcp_client", return_value=mock_client) as mock_get,
        patch("agents.mcp_agent.create_model", return_value=MagicMock()),
        patch("agents.mcp_agent.Agent"),
    ):
        from agents.mcp_agent import create_mcp_agent

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
        patch("agents.mcp_agent.create_mcp_client", return_value=MagicMock()),
        patch("agents.mcp_agent.create_model", return_value=MagicMock()),
        patch("agents.mcp_agent.Agent") as mock_agent_cls,
    ):
        from agents.mcp_agent import create_mcp_agent

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

    from agents.mcp_agent import load_agents_config

    agents = load_agents_config(str(config_path))
    assert len(agents) == 1
    assert agents[0]["name"] == "A1"
