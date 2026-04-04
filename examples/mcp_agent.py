"""Minimal MCP agent — the simplest way to create an A2A agent from an MCP server.

Usage:
    NEON_API_KEY=... python examples/mcp_agent.py
"""

from dotenv import load_dotenv
from strands import Agent

from core.mcp import create_mcp_client
from core.model import create_model
from core.server import serve_agent

load_dotenv()

client = create_mcp_client(
    mcp_url="https://mcp.neon.tech/mcp",
    auth={"type": "bearer", "env_var": "NEON_API_KEY"},
)

agent = Agent(
    model=create_model(),
    name="My MCP Agent",
    description="Queries a database via MCP",
    system_prompt="You are a database assistant. Use the available tools.",
    tools=[client],
    callback_handler=None,
)

serve_agent(agent, name="my-mcp-agent", port=8010)
