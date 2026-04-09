"""Configuration and fixtures for tests.

Run:  pytest tests/ -v
"""

import os
import tempfile
from pathlib import Path

# Set test defaults BEFORE any module imports trigger Settings() creation.
os.environ.setdefault("GOOGLE_API_KEY", "test-google-key")

import pytest
import yaml

# ── Test agents.yaml ─────────────────────────────────────────────────────────

_TEST_AGENTS_CONFIG = {
    "agents": [
        {
            "name": "Test MCP Agent",
            "type": "mcp",
            "port": 9001,
            "description": "Test database agent",
            "mcp_url": "https://example.com/mcp",
            "tools": ["tool_a"],
            "system_prompt": "You are a test agent.",
            "skills": [
                {
                    "id": "test-skill",
                    "name": "Test",
                    "description": "A test skill",
                    "tags": ["test"],
                }
            ],
        },
    ]
}

# Write test config to a temp file at import time so settings can reference it.
_test_config_dir = tempfile.mkdtemp()
_test_config_path = str(Path(_test_config_dir) / "agents.yaml")
Path(_test_config_path).write_text(yaml.dump(_TEST_AGENTS_CONFIG))
os.environ.setdefault("AGENTS_CONFIG", _test_config_path)


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch):
    """Ensure required env vars are set for tests."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("AGENTS_CONFIG", _test_config_path)
