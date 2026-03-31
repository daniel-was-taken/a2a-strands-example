"""Tests for the generic MCP client factory and connection registry."""

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


def test_get_mcp_client_creates_and_caches():
    """get_mcp_client should create a client and cache it by URL."""
    mock_client = MagicMock()
    mock_client._background_thread = MagicMock()
    mock_client._background_thread.is_alive.return_value = True

    with patch("mcp_client.client.create_mcp_client", return_value=mock_client):
        from mcp_client.client import _clients, get_mcp_client

        _clients.clear()
        url = "https://example.com/mcp"

        client1 = get_mcp_client(url)
        client2 = get_mcp_client(url)

        assert client1 is client2
        mock_client.start.assert_called_once()


def test_get_mcp_client_reconnects_on_dead_thread():
    """get_mcp_client should reconnect when the background thread is dead."""
    dead_client = MagicMock()
    dead_client._background_thread = MagicMock()
    dead_client._background_thread.is_alive.return_value = False

    new_client = MagicMock()
    new_client._background_thread = MagicMock()
    new_client._background_thread.is_alive.return_value = True

    with patch("mcp_client.client.create_mcp_client", return_value=new_client):
        from mcp_client.client import _clients, get_mcp_client

        _clients.clear()
        url = "https://reconnect.example.com/mcp"

        # Pre-populate with dead client; get_mcp_client should detect it and reconnect
        _clients[url] = dead_client
        result = get_mcp_client(url)
        assert result is new_client


def test_shutdown_all_stops_all_clients():
    """shutdown_all should stop every registered client."""
    client1 = MagicMock()
    client2 = MagicMock()

    from mcp_client.client import _clients, shutdown_all

    _clients.clear()
    _clients["url1"] = client1
    _clients["url2"] = client2

    shutdown_all()

    client1.stop.assert_called_once()
    client2.stop.assert_called_once()
    assert len(_clients) == 0
