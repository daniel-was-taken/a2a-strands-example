"""Shared Gemini model helpers for Strands agents."""

from google import genai
from strands.models.gemini import GeminiModel
from strands.types.tools import ToolSpec

from core.config import settings


class NoToolsGeminiModel(GeminiModel):
    """Gemini model variant that omits empty tool declarations.

    Some tool-free agents fail when Gemini receives an empty
    ``Tool(function_declarations=[])`` payload. This model suppresses that
    payload entirely when there are no tools configured.
    """

    def _format_request_tools(self, tool_specs: list[ToolSpec] | None) -> list[genai.types.Tool]:
        if not tool_specs and not self.config.get("gemini_tools"):
            return []
        return super()._format_request_tools(tool_specs)


def create_model() -> GeminiModel:
    """Create a GeminiModel configured for the current environment.

    For local development set GOOGLE_API_KEY (Google AI Studio).
    On GCP, Vertex AI uses ADC automatically when GOOGLE_CLOUD_PROJECT is set.
    """
    if settings.google_api_key:
        return GeminiModel(
            client_args={"api_key": settings.google_api_key},
            model_id=settings.gemini_model_id,
        )

    return GeminiModel(
        client_args={
            "vertexai": True,
            "project": settings.google_cloud_project,
            "location": settings.google_cloud_location,
        },
        model_id=settings.gemini_model_id,
    )


def create_toolless_model() -> NoToolsGeminiModel:
    """Create a Gemini model for agents that should not advertise tools."""
    base = create_model()
    return NoToolsGeminiModel(
        client_args=base.client_args,
        model_id=base.config["model_id"],
    )
