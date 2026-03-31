"""Tests for the generic MCP client factory and ReconnectingMCPClient."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_create_mcp_client_no_auth():
    """create_mcp_client without auth should create client with no auth headers."""
    with patch("mcp_client.client.streamable_http_client"):
        from mcp_client.client import create_mcp_client

        client = create_mcp_client("https://example.com/mcp")
        assert client is not None


def test_create_mcp_client_bearer_auth(monkeypatch):
    """create_mcp_client with bearer auth should read token from env."""
    monkeypatch.setenv("MY_TOKEN", "secret-123")
    with patch("mcp_client.client.streamable_http_client"):
        from mcp_client.client import create_mcp_client

        client = create_mcp_client(
            "https://example.com/mcp",
            auth={"type": "bearer", "env_var": "MY_TOKEN"},
        )
        assert client is not None


def test_create_mcp_client_bearer_auth_missing_env():
    """create_mcp_client with bearer auth should raise when env var is missing."""
    import os

    os.environ.pop("MISSING_TOKEN", None)

    with patch("mcp_client.client.streamable_http_client"):
        import pytest

        from mcp_client.client import create_mcp_client

        with pytest.raises(KeyError):
            create_mcp_client(
                "https://example.com/mcp",
                auth={"type": "bearer", "env_var": "MISSING_TOKEN"},
            )


def test_create_mcp_client_returns_reconnecting_subclass():
    """create_mcp_client should return a ReconnectingMCPClient."""
    with patch("mcp_client.client.streamable_http_client"):
        from mcp_client.client import ReconnectingMCPClient, create_mcp_client

        client = create_mcp_client("https://example.com/mcp")
        assert isinstance(client, ReconnectingMCPClient)


def test_reconnecting_client_calls_stop_and_start_on_dead_session():
    """ReconnectingMCPClient should stop+start when session is dead."""
    with patch("mcp_client.client.streamable_http_client"):
        from mcp_client.client import create_mcp_client

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
