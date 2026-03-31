"""Structured JSON logging setup.

Call ``configure_logging(agent_name=...)`` once at process startup to replace
the default plaintext handler with a JSON emitter that includes
``agent_name``, ``task_id``, ``session_id``, and ``duration_ms`` fields as
required by the A2A production checklist.

Usage::

    from common.logging_setup import configure_logging
    configure_logging(agent_name="db-agent")
"""

from __future__ import annotations

import json
import logging
from typing import Any


class StructuredJsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def __init__(self, agent_name: str = "") -> None:
        super().__init__()
        self._agent_name = agent_name

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "agent_name": getattr(record, "agent_name", None) or self._agent_name,
            "task_id": getattr(record, "task_id", "") or "",
            "session_id": getattr(record, "session_id", "") or "",
            "duration_ms": getattr(record, "duration_ms", None),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Drop null/empty values to keep logs concise
        return json.dumps({k: v for k, v in payload.items() if v not in (None, "")})


def configure_logging(agent_name: str = "", level: int = logging.INFO) -> None:
    """Configure the root logger with structured JSON output.

    Args:
        agent_name: Value injected into every log record's ``agent_name`` field.
        level: Minimum log level (default INFO).
    """
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredJsonFormatter(agent_name=agent_name))
    root = logging.getLogger()
    # Clear any existing handlers (e.g. from basicConfig) to avoid duplicates.
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
