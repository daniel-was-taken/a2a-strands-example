"""Generic MCP Agent -- serves any MCP-backed agent as an A2A server.

Reads agent config from agents.yaml and creates a Strands Agent connected
to the specified MCP server. Can be run as a standalone process:

    python -m agents.mcp_agent --config agents.yaml --agent "Database Reader"
"""

from __future__ import annotations

import argparse
import logging

import yaml
from a2a.types import AgentSkill
from strands import Agent

from agents.model import create_model
from mcp_client.client import get_mcp_client

logger = logging.getLogger(__name__)


def load_agents_config(config_path: str = "agents.yaml") -> list[dict]:
    """Load the agents list from a YAML config file."""
    with open(config_path) as f:
        return yaml.safe_load(f)["agents"]


def create_mcp_agent(agent_config: dict) -> Agent:
    """Create a Strands Agent backed by an MCP server.

    Args:
        agent_config: A single agent entry from agents.yaml.
    """
    client = get_mcp_client(
        mcp_url=agent_config["mcp_url"],
        auth=agent_config.get("auth"),
    )
    model = create_model()
    return Agent(
        model=model,
        name=agent_config["name"],
        description=agent_config.get("description", ""),
        system_prompt=agent_config.get("system_prompt", "Use the available tools."),
        tools=[client],
        callback_handler=None,
    )


def serve_mcp_agent(agent_config: dict) -> None:
    """Create and serve an MCP-backed agent as an A2A server."""
    from common.server import serve_agent

    agent = create_mcp_agent(agent_config)
    skills = [AgentSkill(**s) for s in agent_config.get("skills", [])]

    serve_agent(
        agent,
        name=agent_config["name"],
        port=agent_config["port"],
        skills=skills,
    )


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(description="Run an MCP-backed A2A agent")
    parser.add_argument("--config", default="agents.yaml", help="Path to agents.yaml")
    parser.add_argument("--agent", required=True, help="Agent name from config")
    args = parser.parse_args()

    agents = load_agents_config(args.config)
    agent_cfg = next((a for a in agents if a["name"] == args.agent), None)
    if agent_cfg is None:
        raise SystemExit(f"Agent '{args.agent}' not found in {args.config}")
    if agent_cfg["type"] != "mcp":
        raise SystemExit(f"Agent '{args.agent}' is type '{agent_cfg['type']}', not 'mcp'")

    serve_mcp_agent(agent_cfg)
