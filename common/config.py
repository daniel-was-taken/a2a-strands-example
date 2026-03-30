"""Centralised Pydantic Settings for the entire project.

All environment variables are declared here.  Individual modules import
``settings`` rather than calling ``os.environ.get`` scattered across files,
giving a single source of truth and automatic type coercion.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configurable values for the A2A Orchestrator system."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Orchestrator ──────────────────────────────────────────────────────────
    orchestrator_port: int = 8000
    database_mode: str = "a2a"
    #: Comma-separated list of allowed CORS origins.
    allowed_origins: str = "*"
    #: When non-empty, the orchestrator validates this key on every request.
    api_key: str = ""
    rate_limit: str = "30/minute"
    #: Path to the agents YAML config file.
    agents_config: str = "agents.yaml"

    # ── Gemini Model ──────────────────────────────────────────────────────────
    google_api_key: str | None = None
    google_cloud_project: str | None = None
    google_cloud_location: str = "us-central1"
    gemini_model_id: str = "gemini-2.5-flash"

    # ── Query Store ───────────────────────────────────────────────────────────
    store_backend: str = "memory"
    database_url: str | None = None

    # ── Agent-to-Agent Auth ───────────────────────────────────────────────────
    #: Shared secret for inter-agent calls (X-Agent-API-Key header).
    #: When set, every A2AServer validates this header.
    #: Leave empty to disable auth (local dev only).
    agent_api_key: str = ""


settings = Settings()
