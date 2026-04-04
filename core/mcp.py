"""Generic MCP client factory and connection registry.

Connects to any MCP server via Streamable HTTP.  The ``create_mcp_client``
factory returns an ``MCPClient`` subclass that **automatically reconnects**
when the underlying session dies (e.g. idle-timeout from the MCP server).

Usage::

    from core.mcp import create_mcp_client

    client = create_mcp_client(
        "https://mcp.neon.tech/mcp",
        auth={"type": "bearer", "env_var": "NEON_API_KEY"},
    )
    # pass *client* to a Strands Agent — it reconnects transparently
"""

from __future__ import annotations

import contextlib
import logging
import os
from datetime import timedelta
from typing import Any

import httpx
from mcp.client.streamable_http import streamable_http_client
from strands.tools.mcp import MCPClient
from strands.tools.mcp.mcp_client import MCPToolResult

logger = logging.getLogger(__name__)


class ReconnectingMCPClient(MCPClient):
    """MCPClient that transparently reconnects on a dead session.

    ``MCPClient.stop()`` resets all internal state (including ``_init_future``)
    so a subsequent ``start()`` establishes a fresh connection.  This subclass
    intercepts tool calls, detects a dead session, and performs that
    stop → start cycle before retrying.

    Compatible with strands-agents SDK ~0.1.x.
    """

    def _reconnect(self) -> None:
        """Stop the dead session and start a fresh one."""
        logger.warning("MCP session dead — reconnecting")
        with contextlib.suppress(Exception):
            self.stop(None, None, None)
        self.start()
        self._tool_provider_started = True

    async def call_tool_async(
        self,
        tool_use_id: str,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: timedelta | None = None,
    ) -> MCPToolResult:
        """Call a tool, reconnecting first if the session is dead."""
        if not self._is_session_active():
            self._reconnect()
        return await super().call_tool_async(tool_use_id, name, arguments, read_timeout_seconds)


def create_mcp_client(mcp_url: str, auth: dict | None = None) -> ReconnectingMCPClient:
    """Create a reconnecting MCPClient for any MCP server.

    Args:
        mcp_url: The MCP server endpoint URL.
        auth: Optional auth config. Supported types:
              - ``{"type": "bearer", "env_var": "ENV_VAR_NAME"}``
              Raises KeyError if the env var is not set.
    """
    headers: dict[str, str] = {}
    if auth and auth.get("type") == "bearer":
        token = os.environ[auth["env_var"]]
        headers["Authorization"] = f"Bearer {token}"

    # httpx.AsyncClient must be created inside the lambda so it's instantiated
    # in the MCPClient background thread's event loop, not the main thread's.
    return ReconnectingMCPClient(
        lambda: streamable_http_client(
            mcp_url,
            http_client=httpx.AsyncClient(
                timeout=httpx.Timeout(300.0, connect=30.0, read=120.0),
                headers=headers,
            ),
        ),
    )
