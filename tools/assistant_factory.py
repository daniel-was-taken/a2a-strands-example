"""Factory for creating specialist database assistant tools.

Each tool wraps a fresh Strands Agent + MCP client per invocation so that
the orchestrator can route queries to the right specialist.
"""

import logging
from collections.abc import Callable

from strands import Agent, tool
from strands.tools.mcp import MCPClient

from agents.model import create_model
from mcp_client.neon_mcp import BRANCH, DATABASE, PROJECT_ID

logger = logging.getLogger(__name__)

MAX_RETRIES = 2

SHARED_PROMPT_SUFFIX = (
    "\nIMPORTANT: Consider tables from all user-defined schemas.\n"
    "Ignore system/internal schemas (pg_catalog, information_schema, etc.).\n\n"
    "Always query the actual database. Never fabricate schema information.\n"
)


def create_assistant_tool(
    tool_name: str,
    tool_doc: str,
    system_prompt: str,
    query_prefix: str,
    allowed_ops: str,
    mcp_client_factory: Callable[[], MCPClient],
):
    """Create a specialist database tool backed by its own Agent + MCP client.

    Args:
        tool_name: Function name exposed to the orchestrator (e.g. "schema_assistant").
        tool_doc: Docstring shown to the orchestrator for routing.
        system_prompt: System prompt governing the specialist agent.
        query_prefix: Instruction prepended to the user query.
        allowed_ops: Short description of allowed SQL operations for the prompt suffix.
        mcp_client_factory: Callable that creates a fresh Neon MCPClient per invocation.

    Returns:
        A @tool-decorated callable the orchestrator can invoke.
    """

    def _run_with_mcp(formatted_query: str, system_prompt: str) -> str:
        mcp_client = mcp_client_factory()
        with mcp_client:
            # Mark the client as already started so the Agent doesn't try to
            # call start() again (which would raise "session is currently running").
            mcp_client._tool_provider_started = True
            agent = Agent(
                model=create_model(),
                system_prompt=system_prompt,
                tools=[mcp_client],
            )
            return str(agent(formatted_query))

    @tool(name=tool_name)
    def assistant(query: str) -> str:
        formatted_query = (
            f"{query_prefix}{query}\n\n"
            f"Required connection details:\n"
            f"- Project ID: {PROJECT_ID}\n"
            f"- Database: {DATABASE}\n"
            f"- Branch: {BRANCH}\n\n"
            f"{allowed_ops}"
        )

        logger.info("Routed to %s", tool_name)
        last_err: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return _run_with_mcp(formatted_query, system_prompt)
            except RuntimeError as exc:
                if "Connection to the MCP server was closed" not in str(exc):
                    raise
                last_err = exc
                logger.warning(
                    "%s: MCP connection lost (attempt %d/%d), retrying",
                    tool_name,
                    attempt,
                    MAX_RETRIES,
                )
        raise last_err  # type: ignore[misc]

    assistant.__doc__ = tool_doc
    return assistant
