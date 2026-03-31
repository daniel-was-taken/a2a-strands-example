"""Shared helper to start any Strands agent as an A2A server.

Usage::

    from common.server import serve_agent

    agent = Agent(model=model, system_prompt="...", tools=[...])
    serve_agent(agent, name="my-agent", port=8003)
"""

from __future__ import annotations

import uvicorn
from fastapi.middleware.cors import CORSMiddleware
from strands.multiagent.a2a import A2AServer

from common.auth import AgentAuthMiddleware
from common.config import settings
from common.logging_setup import configure_logging
from common.task_store import InMemoryA2ATaskStore
from common.tracing import configure_tracing


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
