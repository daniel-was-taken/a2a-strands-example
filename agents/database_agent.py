"""Database Agent — custom agent backed by the Neon Data API.

Replaces the previous MCP-based Database Agent. Each public tool is a thin
wrapper over ``db.neon.NeonClient``. The agent is registered in ``agents.yaml``
with ``type: custom``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from a2a.types import AgentSkill
from strands import Agent, tool

from core.model import create_model
from db.neon import NeonClient

logger = logging.getLogger(__name__)


def _tool_error(operation: str, exc: BaseException) -> str:
    """Log the underlying exception and return a readable tool-result string.

    Strands tool failures that raise propagate as A2A ``Internal error`` (-32603)
    on the orchestrator side, which hides the cause. Returning ``ERROR: ...``
    keeps the agent turn intact and surfaces the actual failure.
    """
    logger.exception("database_agent_tool_error", extra={"operation": operation})
    return f"ERROR: {type(exc).__name__}: {exc}"

_SYSTEM_PROMPT = (
    "You are DatabaseAgent, a database assistant with full access.\n\n"
    "Use the available tools to inspect schema and execute SQL queries.\n"
    "Consider tables from all user-defined schemas.\n"
    "Ignore system/internal schemas (pg_catalog, information_schema, etc.).\n"
    "Always query the actual database. Never fabricate schema information.\n\n"
    "If an operation fails, report the error clearly and stop.\n"
    "Do not retry the same failing operation."
)

_SKILLS = [
    AgentSkill(
        id="database-ops",
        name="Database Operations",
        description="Schema inspection and SQL queries",
        tags=["database", "sql"],
    ),
]


def _run(coro):
    """Run an async coroutine from the synchronous Strands tool context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # If somehow invoked inside an event loop, schedule and wait.
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()


def _dumps(value: Any) -> str:
    return json.dumps(value, default=str)


def _client() -> NeonClient:
    return NeonClient()


@tool
def get_database_tables() -> str:
    """List every user-defined table with its schema.

    Returns:
        JSON array of ``{"table_schema", "table_name"}`` objects.
    """
    try:
        rows = _run(_client().get_database_tables())
    except Exception as exc:
        return _tool_error("get_database_tables", exc)
    return _dumps(rows)


@tool
def describe_table_schema(schema: str, table: str) -> str:
    """Describe columns of a table.

    Args:
        schema: Postgres schema name (e.g. ``public``).
        table: Table name.

    Returns:
        JSON array of ``{"column_name", "data_type", "is_nullable"}`` objects.
    """
    try:
        rows = _run(_client().describe_table_schema(schema, table))
    except Exception as exc:
        return _tool_error("describe_table_schema", exc)
    return _dumps(rows)


@tool
def run_sql(query: str) -> str:
    """Execute an arbitrary SQL statement and return the rows as JSON.

    Args:
        query: SQL statement to execute.

    Returns:
        JSON array of row dicts, or an ``ERROR: ...`` string on failure.
    """
    try:
        rows = _run(_client().run_sql(query))
    except Exception as exc:
        return _tool_error("run_sql", exc)
    return _dumps(rows)


def create_agent() -> Agent:
    """Build the Database Agent with Neon-backed tools."""
    return Agent(
        model=create_model(),
        name="Database Agent",
        description="Full database access: schema inspection, SELECT, INSERT, DELETE queries",
        system_prompt=_SYSTEM_PROMPT,
        tools=[get_database_tables, describe_table_schema, run_sql],
        load_tools_from_directory=False,
        callback_handler=None,
    )


def serve() -> None:
    """Start the Database Agent as an A2A server."""
    from core.server import serve_agent

    serve_agent(
        create_agent(),
        name="Database Agent",
        port=8001,
        skills=_SKILLS,
    )


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    serve()
