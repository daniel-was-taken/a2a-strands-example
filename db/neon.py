"""Neon Data API client.

Uses the Neon SQL-over-HTTP endpoint to talk directly to a Postgres database
without MCP. Connection settings come from ``core/config.py``.

The three public helpers mirror the MCP tools the Database Agent used to call:
``get_database_tables``, ``describe_table_schema``, and ``run_sql``.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_MAX_ATTEMPTS = 4
_WRITE_PATTERN = re.compile(
    r"^\s*(insert|update|delete|drop|truncate|alter|create|grant|revoke)\b",
    re.IGNORECASE,
)


class NeonDataApiError(RuntimeError):
    """Raised when the Neon Data API returns a non-recoverable error."""


class NeonClient:
    """Thin async client for the Neon SQL-over-HTTP endpoint.

    Args:
        database_url: Full Neon SQL-over-HTTP URL (e.g. ``https://<project>.neon.tech/sql``).
        connection_string: Postgres connection string sent in the
            ``Neon-Connection-String`` header (e.g.
            ``postgresql://user:pass@<host>/<db>?sslmode=require``).
        read_only: When true, any write SQL statement is rejected before being sent.
    """

    def __init__(
        self,
        database_url: str | None = None,
        connection_string: str | None = None,
        *,
        read_only: bool = False,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._database_url = database_url or settings.neon_database_url
        self._connection_string = connection_string or settings.neon_connection_string
        self._read_only = read_only
        self._client = client

    def _require_config(self) -> tuple[str, str]:
        if not self._database_url:
            raise NeonDataApiError("NEON_DATABASE_URL is not configured")
        if not self._connection_string:
            raise NeonDataApiError("NEON_CONNECTION_STRING is not configured")
        return self._database_url, self._connection_string

    async def _request(self, sql: str, params: list[Any] | None) -> list[dict[str, Any]]:
        database_url, connection_string = self._require_config()

        payload: dict[str, Any] = {"query": sql}
        if params is not None:
            payload["params"] = params

        headers = {
            "Neon-Connection-String": connection_string,
            "Neon-Raw-Text-Output": "false",
            "Neon-Array-Mode": "false",
            "Content-Type": "application/json",
        }

        last_exc: Exception | None = None
        client = self._client or httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
        owns_client = self._client is None
        try:
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                start = time.perf_counter()
                retried = attempt > 1
                try:
                    response = await client.post(database_url, json=payload, headers=headers)
                except httpx.RequestError as exc:
                    last_exc = exc
                    logger.warning(
                        "neon_data_api_request_error",
                        extra={
                            "attempt": attempt,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        },
                    )
                    if attempt == _MAX_ATTEMPTS:
                        raise NeonDataApiError(
                            f"Neon Data API {type(exc).__name__}: {exc}"
                        ) from exc
                    await _sleep_backoff(attempt)
                    continue

                duration_ms = (time.perf_counter() - start) * 1000
                if response.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
                    logger.warning(
                        "neon_data_api_retry",
                        extra={
                            "attempt": attempt,
                            "status": response.status_code,
                            "duration_ms": duration_ms,
                        },
                    )
                    await _sleep_backoff(attempt)
                    continue

                logger.info(
                    "neon_data_api_call",
                    extra={
                        "duration_ms": duration_ms,
                        "status": response.status_code,
                        "retried": retried,
                    },
                )

                if response.status_code >= 400:
                    raise NeonDataApiError(
                        f"Neon Data API returned {response.status_code}: {response.text}"
                    )

                body = response.json()
                rows = body.get("rows")
                if rows is None:
                    return []
                return list(rows)

            raise NeonDataApiError(f"Neon Data API failed after {_MAX_ATTEMPTS} attempts")
        finally:
            if owns_client:
                await client.aclose()
        # Unreachable but keeps mypy satisfied.
        if last_exc is not None:
            raise NeonDataApiError(str(last_exc))
        raise NeonDataApiError("Neon Data API request failed")

    async def get_database_tables(self) -> list[dict[str, Any]]:
        """Return every user table with ``table_schema`` and ``table_name``."""
        sql = (
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
            "ORDER BY table_schema, table_name"
        )
        return await self._request(sql, params=None)

    async def describe_table_schema(self, schema: str, table: str) -> list[dict[str, Any]]:
        """Return columns (name, type, nullability) for ``schema.table``."""
        sql = (
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = $1 AND table_name = $2 ORDER BY ordinal_position"
        )
        return await self._request(sql, params=[schema, table])

    async def run_sql(self, query: str) -> list[dict[str, Any]]:
        """Execute arbitrary SQL and return rows as dicts.

        When ``read_only`` is true, write statements are rejected before the call.
        """
        if self._read_only and _WRITE_PATTERN.match(query):
            raise NeonDataApiError("Read-only mode: write statements are not permitted")
        return await self._request(query, params=None)


async def _sleep_backoff(attempt: int) -> None:
    import asyncio

    delay = min(2 ** (attempt - 1), 8)
    await asyncio.sleep(delay)
