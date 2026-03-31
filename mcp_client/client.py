"""Generic MCP client factory and connection registry.

Connects to any MCP server via Streamable HTTP. Clients are cached by URL
and auto-reconnect when the background thread dies.

Usage::

    from mcp_client.client import get_mcp_client, shutdown_all

    client = get_mcp_client(
        "https://mcp.neon.tech/mcp",
        auth={"type": "bearer", "env_var": "NEON_API_KEY"},
    )
    # ... use client with Strands Agent ...
    shutdown_all()  # at process exit
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import os
import threading

import httpx
from mcp.client.streamable_http import streamable_http_client
from strands.tools.mcp import MCPClient

logger = logging.getLogger(__name__)

_clients: dict[str, MCPClient] = {}
_lock = threading.Lock()
_SENTINEL = object()


def create_mcp_client(mcp_url: str, auth: dict | None = None) -> MCPClient:
    """Create an MCPClient for any MCP server.

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

    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(300.0, connect=30.0, read=120.0),
        headers=headers,
    )
    return MCPClient(
        lambda: streamable_http_client(mcp_url, http_client=http_client),
    )


def _is_healthy(client: MCPClient) -> bool:
    """Return True if the client's background thread is still running.

    Note: accesses private ``_background_thread`` attr (strands-agents ~0.1.x).
    """
    thread = client._background_thread
    return thread is not None and thread.is_alive()


def get_mcp_client(mcp_url: str, auth: dict | None = None) -> MCPClient:
    """Return a live MCPClient for the given URL, creating or reconnecting as needed.

    Clients are cached by URL. Multiple agents sharing the same MCP URL
    reuse one connection.
    """
    with _lock:
        client = _clients.get(mcp_url)
        if client is not None and _is_healthy(client):
            return client

        if client is not None:
            logger.warning("MCP connection lost for %s, reconnecting", mcp_url)
            with contextlib.suppress(Exception):
                client.stop(None, None, None)

        logger.info("Starting MCP connection to %s", mcp_url)
        client = create_mcp_client(mcp_url, auth)
        client.start()
        client._tool_provider_started = True
        client.add_consumer(_SENTINEL)
        _clients[mcp_url] = client
        return client


def shutdown_all() -> None:
    """Gracefully shut down all MCP connections."""
    with _lock:
        for url, client in _clients.items():
            logger.info("Shutting down MCP connection to %s", url)
            try:
                client._consumers.discard(_SENTINEL)
                client.stop(None, None, None)
            except Exception:
                logger.debug("MCP shutdown error for %s (ignored)", url, exc_info=True)
        _clients.clear()


atexit.register(shutdown_all)
