"""Test that serve_agent derives correct http_url from port."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_a2a_server_receives_derived_url_when_http_url_is_none():
    """When http_url is None, A2AServer should receive http://127.0.0.1:{port}/."""
    with (
        patch("common.server.configure_logging"),
        patch("common.server.configure_tracing"),
        patch("common.server.A2AServer") as mock_a2a,
        patch("common.server.uvicorn"),
    ):
        mock_a2a.return_value.to_fastapi_app.return_value = MagicMock()

        from common.server import serve_agent

        serve_agent(MagicMock(), name="test", port=8001)

        mock_a2a.assert_called_once()
        call_kwargs = mock_a2a.call_args[1]
        assert call_kwargs["http_url"] == "http://127.0.0.1:8001/"


def test_a2a_server_uses_explicit_http_url():
    """When http_url is provided, A2AServer should use it as-is."""
    with (
        patch("common.server.configure_logging"),
        patch("common.server.configure_tracing"),
        patch("common.server.A2AServer") as mock_a2a,
        patch("common.server.uvicorn"),
    ):
        mock_a2a.return_value.to_fastapi_app.return_value = MagicMock()

        from common.server import serve_agent

        serve_agent(MagicMock(), name="test", port=8001, http_url="https://api.example.com/")

        call_kwargs = mock_a2a.call_args[1]
        assert call_kwargs["http_url"] == "https://api.example.com/"
