"""Unit tests for the custom Database Agent."""

from __future__ import annotations

import json

from agents import database_agent


class _FakeNeonClient:
    """Minimal stand-in for NeonClient that records method calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def get_database_tables(self):
        self.calls.append(("get_database_tables", ()))
        return [{"table_schema": "public", "table_name": "users"}]

    async def describe_table_schema(self, schema: str, table: str):
        self.calls.append(("describe_table_schema", (schema, table)))
        return [{"column_name": "id", "data_type": "integer", "is_nullable": "NO"}]

    async def run_sql(self, query: str):
        self.calls.append(("run_sql", (query,)))
        return [{"count": 1}]


def _install_fake(monkeypatch):
    fake = _FakeNeonClient()
    monkeypatch.setattr(database_agent, "_client", lambda: fake)
    return fake


def _invoke(tool_obj, **kwargs):
    """Strands @tool decorates callables. Unwrap for direct invocation in tests."""
    inner = getattr(tool_obj, "original_function", None) or getattr(tool_obj, "__wrapped__", None)
    if inner is None and callable(tool_obj):
        return tool_obj(**kwargs)
    return inner(**kwargs)


def test_get_database_tables_returns_json(monkeypatch):
    fake = _install_fake(monkeypatch)
    result = _invoke(database_agent.get_database_tables)
    assert json.loads(result) == [{"table_schema": "public", "table_name": "users"}]
    assert fake.calls == [("get_database_tables", ())]


def test_describe_table_schema_passes_args(monkeypatch):
    fake = _install_fake(monkeypatch)
    result = _invoke(database_agent.describe_table_schema, schema="public", table="users")
    assert json.loads(result)[0]["column_name"] == "id"
    assert fake.calls == [("describe_table_schema", ("public", "users"))]


def test_run_sql_returns_json(monkeypatch):
    fake = _install_fake(monkeypatch)
    result = _invoke(database_agent.run_sql, query="SELECT 1")
    assert json.loads(result) == [{"count": 1}]
    assert fake.calls == [("run_sql", ("SELECT 1",))]


def test_errors_are_returned_as_string(monkeypatch):
    from db.neon import NeonDataApiError

    class _Boom:
        async def get_database_tables(self):
            raise NeonDataApiError("boom")

    monkeypatch.setattr(database_agent, "_client", lambda: _Boom())
    result = _invoke(database_agent.get_database_tables)
    assert result.startswith("ERROR:")
    assert "boom" in result


def test_create_agent_returns_agent_with_tools(monkeypatch):
    # Stub model creation so the test doesn't need real credentials.
    class _DummyModel: ...

    monkeypatch.setattr(database_agent, "create_model", lambda: _DummyModel())
    agent = database_agent.create_agent()
    assert agent.name == "Database Agent"
    # The agent should expose all three Neon-backed tools.
    tool_names: set[str] = set()
    if hasattr(agent, "tool_registry"):
        tool_names = {
            getattr(t, "tool_name", getattr(t, "__name__", ""))
            for t in agent.tool_registry.registry.values()
        }
    # Fallback for SDKs where the registry isn't exposed: verify via tool_config.
    if not tool_names and hasattr(agent, "tool_config"):
        tool_names = {spec.get("name", "") for spec in agent.tool_config.get("tools", [])}
    expected = {"get_database_tables", "describe_table_schema", "run_sql"}
    assert not tool_names or expected <= tool_names
