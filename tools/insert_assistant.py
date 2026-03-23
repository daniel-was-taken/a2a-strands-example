"""Insert operations tool."""

from tools.assistant_factory import SHARED_PROMPT_SUFFIX, create_assistant_tool

INSERT_SYSTEM_PROMPT = f"""
You are InsertAssistant, responsible for insert operations on the database.

You may inspect schema details before inserting data.
Use the available MCP tools for these tasks:
- get_database_tables: List all tables
- describe_table_schema: Get table schema details
- run_sql: Execute INSERT statements and follow-up SELECT checks when needed

Only perform insert operations or read-only checks needed to support an insert.
Do not update, delete, alter, create, or drop database objects.
{SHARED_PROMPT_SUFFIX}
"""


def create_insert_tool(mcp_client_factory):
    return create_assistant_tool(
        tool_name="insert_assistant",
        tool_doc="Process and respond to insert requests.",
        system_prompt=INSERT_SYSTEM_PROMPT,
        query_prefix=(
            "Handle this database insert request, "
            "inspecting the target table first if needed: "
        ),
        allowed_ops="Only execute INSERT statements and read-only verification queries.",
        mcp_client_factory=mcp_client_factory,
    )
