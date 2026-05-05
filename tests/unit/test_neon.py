"""Unit tests for db.neon.NeonClient."""

from __future__ import annotations

import httpx
import pytest

from db.neon import NeonClient, NeonDataApiError


def _mock_transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_get_database_tables_issues_expected_sql():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = request.content
        captured["conn"] = request.headers.get("Neon-Connection-String")
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"rows": [{"table_schema": "public", "table_name": "t"}]})

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as client:
        neon = NeonClient(
            database_url="https://example.neon.tech/sql",
            connection_string="postgresql://u:p@example.neon.tech/db",
            client=client,
        )
        rows = await neon.get_database_tables()

    assert rows == [{"table_schema": "public", "table_name": "t"}]
    assert b"information_schema.tables" in captured["payload"]
    assert captured["conn"] == "postgresql://u:p@example.neon.tech/db"
    assert captured["auth"] is None


@pytest.mark.asyncio
async def test_describe_table_schema_passes_parameters():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json={"rows": []})

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as client:
        neon = NeonClient(
            database_url="https://example.neon.tech/sql",
            connection_string="postgresql://u:p@example.neon.tech/db",
            client=client,
        )
        await neon.describe_table_schema("public", "users")

    assert captured["body"]["params"] == ["public", "users"]
    assert "information_schema.columns" in captured["body"]["query"]


@pytest.mark.asyncio
async def test_run_sql_read_only_rejects_writes():
    transport = _mock_transport(lambda r: httpx.Response(200))
    async with httpx.AsyncClient(transport=transport) as client:
        neon = NeonClient(
            database_url="https://example.neon.tech/sql",
            connection_string="postgresql://u:p@example.neon.tech/db",
            read_only=True,
            client=client,
        )
        with pytest.raises(NeonDataApiError, match="Read-only"):
            await neon.run_sql("DELETE FROM users")


@pytest.mark.asyncio
async def test_retries_on_retryable_status():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"rows": [{"ok": 1}]})

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as client:
        neon = NeonClient(
            database_url="https://example.neon.tech/sql",
            connection_string="postgresql://u:p@example.neon.tech/db",
            client=client,
        )
        rows = await neon.run_sql("SELECT 1")

    assert rows == [{"ok": 1}]
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_raises_on_non_retryable_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="syntax error")

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as client:
        neon = NeonClient(
            database_url="https://example.neon.tech/sql",
            connection_string="postgresql://u:p@example.neon.tech/db",
            client=client,
        )
        with pytest.raises(NeonDataApiError, match="400"):
            await neon.run_sql("SLECT 1")


@pytest.mark.asyncio
async def test_missing_config_raises():
    neon = NeonClient(database_url=None, connection_string=None)
    with pytest.raises(NeonDataApiError):
        await neon.run_sql("SELECT 1")
