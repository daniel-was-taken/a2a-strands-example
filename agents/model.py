"""Shared model configuration for all Strands agents.

Uses centralised settings from ``common.config``.
Set GOOGLE_API_KEY for local dev, or use Vertex AI on GCP (ADC auto-detected).
"""

from strands.models.gemini import GeminiModel

from common.config import settings


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
