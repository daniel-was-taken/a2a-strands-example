"""Unit tests for tool-free custom agents."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_create_toolless_model_returns_no_tools_variant(monkeypatch):
    import core.model as model_module

    monkeypatch.setattr(model_module.settings, "google_api_key", "test-key")
    monkeypatch.setattr(model_module.settings, "google_cloud_project", None)
    monkeypatch.setattr(model_module.settings, "gemini_model_id", "gemini-test")

    model = model_module.create_toolless_model()

    assert isinstance(model, model_module.NoToolsGeminiModel)
    assert model.client_args == {"api_key": "test-key"}
    assert model.config["model_id"] == "gemini-test"


def test_brd_specialist_uses_toolless_model_configuration():
    mock_model = MagicMock()

    with (
        patch("agents.brd_specialist.create_toolless_model", return_value=mock_model),
        patch("agents.brd_specialist.Agent") as mock_agent,
    ):
        from agents.brd_specialist import create_agent

        create_agent()

    call_kwargs = mock_agent.call_args.kwargs
    assert call_kwargs["model"] is mock_model
    assert call_kwargs["tools"] == []
    assert call_kwargs["load_tools_from_directory"] is False


def test_research_team_uses_toolless_agents():
    mock_model = MagicMock()

    with (
        patch("agents.research_team.create_toolless_model", return_value=mock_model),
        patch("agents.research_team.Agent") as mock_agent,
        patch("agents.research_team.Swarm") as mock_swarm,
    ):
        from agents.research_team import create_agent

        create_agent()

    assert mock_agent.call_count == 3
    for call in mock_agent.call_args_list:
        assert call.kwargs["model"] is mock_model
        assert call.kwargs["tools"] == []
        assert call.kwargs["load_tools_from_directory"] is False
    mock_swarm.assert_called_once()
