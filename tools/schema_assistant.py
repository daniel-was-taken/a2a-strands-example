"""Read-only schema inspection tool."""

from tools.assistant_factory import SHARED_PROMPT_SUFFIX, create_assistant_tool

SCHEMA_SYSTEM_PROMPT = f"""
You are SchemaAssistant, responsible for running read-only queries on the database.

Use the available MCP tools to execute read-only SELECT queries and retrieve schema information:
- get_database_tables: List all tables
- describe_table_schema: Get table schema details
- run_sql: Execute SELECT queries only
{SHARED_PROMPT_SUFFIX}
"""


def create_schema_tool(mcp_client_factory):
    return create_assistant_tool(
        tool_name="schema_assistant",
        tool_doc=(
            "Process and respond to read-only schema and data inspection queries.\n\n"
            "Args:\n    query: A request for schema inspection or read-only data access\n\n"
            "Returns:\n    Query results or schema details from the database"
        ),
        system_prompt=SCHEMA_SYSTEM_PROMPT,
        query_prefix=(
            "Please answer this database schema request, "
            "showing all steps and explaining clearly: "
        ),
        allowed_ops="Use only read-only queries. For SQL, execute SELECT statements only.",
        mcp_client_factory=mcp_client_factory,
    )
