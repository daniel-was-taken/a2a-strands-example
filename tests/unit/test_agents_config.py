"""Tests for agents.yaml config loading."""

from __future__ import annotations

from pathlib import Path

import yaml


def _write_config(tmp_path: Path, config: dict) -> Path:
    """Write a YAML config to a temp file and return the path."""
    config_path = tmp_path / "agents.yaml"
    config_path.write_text(yaml.dump(config))
    return config_path


def test_load_valid_agents_config(tmp_path):
    """Valid agents.yaml should parse correctly."""
    config = {
        "agents": [
            {
                "name": "Test Agent",
                "type": "mcp",
                "port": 9001,
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
    config_path = _write_config(tmp_path, config)
    loaded = yaml.safe_load(config_path.read_text())
    assert len(loaded["agents"]) == 1
    assert loaded["agents"][0]["name"] == "Test Agent"
    assert loaded["agents"][0]["type"] == "mcp"


def test_load_custom_agent_config(tmp_path):
    """Custom agent entries should have module and factory fields."""
    config = {
        "agents": [
            {
                "name": "Custom Agent",
                "type": "custom",
                "port": 9002,
                "module": "agents.graph_agent",
                "factory": "create_graph_agent",
                "skills": [],
            },
        ]
    }
    config_path = _write_config(tmp_path, config)
    loaded = yaml.safe_load(config_path.read_text())
    agent = loaded["agents"][0]
    assert agent["type"] == "custom"
    assert agent["module"] == "agents.graph_agent"
    assert agent["factory"] == "create_graph_agent"


def test_repo_database_agent_is_custom():
    """The checked-in agents.yaml should register the Database Agent as custom."""
    repo_config = Path(__file__).resolve().parents[2] / "agents.yaml"
    loaded = yaml.safe_load(repo_config.read_text())
    db_agent = next(a for a in loaded["agents"] if a["name"] == "Database Agent")
    assert db_agent["type"] == "custom"
    assert db_agent["module"] == "agents.database_agent"
    assert db_agent["factory"] == "create_agent"
    # Neon-specific MCP fields should no longer be present on the Database Agent.
    assert "mcp_url" not in db_agent
    assert "auth" not in db_agent
    assert "tools" not in db_agent


def test_load_agents_config_with_auth(tmp_path):
    """Auth block should be parsed correctly."""
    config = {
        "agents": [
            {
                "name": "Auth Agent",
                "type": "mcp",
                "port": 9003,
                "mcp_url": "https://example.com/mcp",
                "auth": {"type": "bearer", "env_var": "MY_TOKEN"},
                "tools": ["tool_a"],
                "skills": [],
            },
        ]
    }
    config_path = _write_config(tmp_path, config)
    loaded = yaml.safe_load(config_path.read_text())
    agent = loaded["agents"][0]
    assert agent["auth"]["type"] == "bearer"
    assert agent["auth"]["env_var"] == "MY_TOKEN"
