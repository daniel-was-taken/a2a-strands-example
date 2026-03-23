"""Delete operations tool."""

from tools.assistant_factory import SHARED_PROMPT_SUFFIX, create_assistant_tool

DELETE_SYSTEM_PROMPT = f"""
You are DeleteAssistant, responsible for delete operations on the database.

You may inspect schema details before deleting data.
Use the available MCP tools for these tasks:
- get_database_tables: List all tables
- describe_table_schema: Get table schema details
- run_sql: Execute DELETE statements and follow-up SELECT checks when needed

Only perform delete operations or read-only checks needed to support a delete.
Do not insert, update, alter, create, or drop database objects.
{SHARED_PROMPT_SUFFIX}
"""


def create_delete_tool(mcp_client_factory):
    return create_assistant_tool(
        tool_name="delete_assistant",
        tool_doc="Process and respond to delete requests.",
        system_prompt=DELETE_SYSTEM_PROMPT,
        query_prefix=(
            "Handle this database delete request, "
            "inspecting the target table first if needed: "
        ),
        allowed_ops="Only execute DELETE statements and read-only verification queries.",
        mcp_client_factory=mcp_client_factory,
    )
