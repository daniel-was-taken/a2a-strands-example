"""Centralised Pydantic Settings for the A2A agent framework.

All environment variables are declared here.  Individual modules import
``settings`` rather than calling ``os.environ.get`` scattered across files,
giving a single source of truth and automatic type coercion.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configurable values for the A2A agent framework."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Agent Serving ─────────────────────────────────────────────────────────
    #: Comma-separated list of allowed CORS origins.
    allowed_origins: str = "*"
    #: Path to the agents YAML config file.
    agents_config: str = "agents.yaml"

    # ── Gemini Model ──────────────────────────────────────────────────────────
    google_api_key: str | None = None
    google_cloud_project: str | None = None
    google_cloud_location: str = "us-central1"
    gemini_model_id: str = "gemini-2.5-flash"

    # ── Agent-to-Agent Auth ───────────────────────────────────────────────────
    #: Shared secret for inter-agent calls (X-Agent-API-Key header).
    #: When set, every A2AServer validates this header.
    #: Leave empty to disable auth (local dev only).
    agent_api_key: str = ""


settings = Settings()
