"""Neon MCP client factory for connecting sub-agents to the Neon database.

Required env vars: NEON_API_KEY, NEON_PROJECT_ID, NEON_DATABASE, NEON_BRANCH_ID.
"""

import os

import httpx
from mcp.client.streamable_http import streamable_http_client
from strands.tools.mcp import MCPClient

PROJECT_ID = os.environ.get("NEON_PROJECT_ID", "")
DATABASE = os.environ.get("NEON_DATABASE", "")
BRANCH = os.environ.get("NEON_BRANCH_ID", "")

NEON_MCP_URL = os.environ.get("NEON_MCP_URL", "https://mcp.neon.tech/mcp")


def create_neon_mcp_client() -> MCPClient:
    """Create a fresh Neon MCPClient for a single agent invocation."""
    api_key = os.environ["NEON_API_KEY"]
    return MCPClient(
        lambda: streamable_http_client(
            NEON_MCP_URL,
            http_client=httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=30.0),
                limits=httpx.Limits(max_keepalive_connections=0),
                headers={"Authorization": f"Bearer {api_key}"},
            ),
        ),
    )
