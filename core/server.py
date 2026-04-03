"""Shared helpers to create and serve MCP-backed Strands agents as A2A servers.

Combines the generic serve_agent() helper with the MCP agent factory so that
specialist agents can be declared entirely in agents.yaml and launched with::

    python -m core.server --config agents.yaml --agent "Database Reader"

Or imported programmatically::

    from core.server import serve_agent, create_mcp_agent, serve_mcp_agent
"""

from __future__ import annotations

import argparse
import logging

import uvicorn
import yaml
from a2a.types import AgentSkill
from fastapi.middleware.cors import CORSMiddleware
from strands import Agent
from strands.multiagent.a2a import A2AServer

from core.auth import AgentAuthMiddleware
from core.config import settings
from core.logging import configure_logging
from core.mcp import create_mcp_client
from core.model import create_model
from core.task_store import InMemoryA2ATaskStore
from core.tracing import configure_tracing

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
    client = create_mcp_client(
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
    agent = create_mcp_agent(agent_config)
    skills = [AgentSkill(**s) for s in agent_config.get("skills", [])]

    serve_agent(
        agent,
        name=agent_config["name"],
        port=agent_config["port"],
        skills=skills,
    )


def serve_agent(
    agent,
    *,
    name: str,
    port: int,
    http_url: str | None = None,
    skills: list | None = None,
    version: str = "1.0.0",
) -> None:
    """Start a Strands agent as an A2A server with auth, CORS, and structured logging.

    Args:
        agent: A Strands Agent (or Graph) instance.
        name: Display name used in logs and AgentCard.
        port: TCP port to bind.
        http_url: Public URL advertised in the AgentCard (optional).
        skills: List of AgentSkill entries for the AgentCard.
        version: Semver version for the AgentCard.
    """
    configure_logging(agent_name=name)
    configure_tracing(service_name=name)

    a2a_server = A2AServer(
        agent=agent,
        http_url=http_url or f"http://127.0.0.1:{port}/",
        version=version,
        skills=skills or [],
        task_store=InMemoryA2ATaskStore(),
        enable_a2a_compliant_streaming=True,
    )

    app = a2a_server.to_fastapi_app()
    app.add_middleware(AgentAuthMiddleware, api_key=settings.agent_api_key)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins.split(","),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    uvicorn.run(app, host="0.0.0.0", port=port)


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
