"""Shared Gemini model configuration for all Strands agents.

Set GOOGLE_API_KEY for local dev, or use Vertex AI on GCP (ADC auto-detected).
"""

import os

from strands.models.gemini import GeminiModel

MODEL_ID = os.environ.get("GEMINI_MODEL_ID", "gemini-2.5-flash")


def create_model() -> GeminiModel:
    """Create a GeminiModel configured for the current environment.

    For local development set GOOGLE_API_KEY (Google AI Studio).
    On GCP, Vertex AI uses ADC automatically when GOOGLE_CLOUD_PROJECT is set.
    """
    api_key = os.environ.get("GOOGLE_API_KEY")
    if api_key:
        return GeminiModel(
            client_args={"api_key": api_key},
            model_id=MODEL_ID,
        )

    return GeminiModel(
        client_args={
            "vertexai": True,
            "project": os.environ.get("GOOGLE_CLOUD_PROJECT"),
            "location": os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        },
        model_id=MODEL_ID,
    )
