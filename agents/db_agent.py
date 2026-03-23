"""Database Agent -- exposed as an A2A server on port 8001.

This agent connects to the Neon MCP service and provides specialist
database tools (schema, insert, delete) to other agents via the A2A protocol.
"""

import logging
import os

from strands import Agent
from strands.multiagent.a2a import A2AServer
from strands.tools.executors import SequentialToolExecutor

from agents.model import create_model
from mcp_client.neon_mcp import create_neon_mcp_client
from tools.delete_assistant import create_delete_tool
from tools.insert_assistant import create_insert_tool
from tools.schema_assistant import create_schema_tool

logger = logging.getLogger(__name__)

DATABASE_AGENT_PORT = int(os.environ.get("DATABASE_AGENT_PORT", "8001"))

DATABASE_SYSTEM_PROMPT = """
You are DatabaseAgent, a specialist database management agent.

You handle all database-related requests by routing them to the appropriate tool:
- schema_assistant: for read-only schema inspection and SELECT queries
- insert_assistant: for INSERT operations
- delete_assistant: for DELETE operations

Always use the correct tool for the request type.
Keep responses clear and actionable.
"""


def create_database_agent() -> Agent:
    """Build the database agent with MCP-backed specialist tools."""
    model = create_model()
    return Agent(
        model=model,
        name="Database Agent",
        description="Handles database operations including schema queries, inserts, and deletes",
        system_prompt=DATABASE_SYSTEM_PROMPT,
        tool_executor=SequentialToolExecutor(),
        tools=[
            create_schema_tool(create_neon_mcp_client),
            create_insert_tool(create_neon_mcp_client),
            create_delete_tool(create_neon_mcp_client),
        ],
    )


def serve():
    """Start the Database Agent as an A2A server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("Starting Database Agent A2A server on port %d", DATABASE_AGENT_PORT)

    agent = create_database_agent()
    a2a_server = A2AServer(agent=agent, enable_a2a_compliant_streaming=True)
    a2a_server.serve(host="0.0.0.0", port=DATABASE_AGENT_PORT)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    serve()
