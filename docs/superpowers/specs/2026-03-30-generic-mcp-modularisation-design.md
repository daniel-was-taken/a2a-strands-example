# Generic MCP Modularisation Design

**Date:** 2026-03-30
**Status:** Draft

## Problem

Two issues:

1. **Bug**: `A2AServer` defaults to `http://127.0.0.1:9000/` when no `http_url` is provided. Both agents advertise this wrong URL in their agent cards, so the orchestrator's A2A client sends messages to port 9000 where nothing is listening.

2. **Coupling**: The system is hardcoded to Neon PostgreSQL. Adding a different MCP server or new agent requires writing new Python modules. The agent topology is scattered across `common/config.py`, `run_system.py`, and each agent module.

## Solution

A YAML-driven architecture where:

- Agents are declared in `agents.yaml` (MCP-backed or custom Python)
- A generic MCP client connects to any MCP server
- A generic MCP agent factory creates Strands Agents from config
- The orchestrator and runner discover agents dynamically from the same YAML

## `agents.yaml` Config Format

```yaml
agents:
  # MCP-backed agents (no code needed)
  - name: "Database Reader"
    type: mcp
    port: 8001
    description: "Read-only database access: schema inspection and SELECT queries"
    mcp_url: "https://mcp.neon.tech/mcp"
    auth:
      type: bearer
      env_var: NEON_API_KEY
    tools: ["get_database_tables", "describe_table_schema", "run_sql"]
    system_prompt: "You are a read-only database assistant. Only run SELECT queries."
    skills:
      - id: schema-query
        name: Schema Query
        description: "Inspect database schema and run read-only SELECT queries"
        tags: [database, schema, read-only]

  - name: "Database Writer"
    type: mcp
    port: 8003
    description: "Write operations: INSERT records into database tables"
    mcp_url: "https://mcp.neon.tech/mcp"
    auth:
      type: bearer
      env_var: NEON_API_KEY
    tools: ["describe_table_schema", "run_sql"]
    system_prompt: "You handle INSERT operations only. Inspect schema before inserting."
    skills:
      - id: data-insert
        name: Data Insert
        description: "Insert records into database tables"
        tags: [database, insert, write]

  # Custom agents (Python factory function)
  - name: "Graph Agent"
    type: custom
    port: 8002
    module: "agents.graph_agent"
    factory: "create_graph_agent"
    skills:
      - id: multi-step-reasoning
        name: Multi-Step Reasoning
        description: "Analyze, implement, and review through a structured graph workflow"
        tags: [reasoning, analysis, review]
```

### Agent types

- **`mcp`**: Declares an MCP server URL, auth, tool filter, and system prompt. The framework creates a Strands Agent automatically.
- **`custom`**: Points to a Python `module` and `factory` function. The factory returns an Agent, Graph, or Swarm. The framework wraps it with `serve_agent()`.

### Auth block

Extensible. Currently supports:
- `bearer`: Reads a token from the env var named in `env_var` and sends it as `Authorization: Bearer <token>`.
- Omit for unauthenticated MCP servers.

### Tool filtering

The `tools` list specifies which MCP tools the agent should use. Enforced via the system prompt (the LLM is told which operations are allowed). The list also serves as documentation. Physical tool filtering can be added later if MCPClient supports it.

## Bug Fix: Agent Card URL

In `common/server.py`, when `http_url` is `None`, derive it from the port:

```python
a2a_server = A2AServer(
    agent=agent,
    http_url=http_url or f"http://127.0.0.1:{port}/",
    ...
)
```

Per-agent `http_url` overrides in YAML (or env vars) still work for production deployments where agents are behind a reverse proxy. An optional `http_url` field can be added to any agent entry in YAML to override the derived URL.

## Generic MCP Client (`mcp_client/client.py`)

Replaces `mcp_client/neon_mcp.py`. Same singleton/reconnect pattern, parameterised by URL and auth.

### Factory

```python
def create_mcp_client(mcp_url: str, auth: dict | None = None) -> MCPClient:
    headers = {}
    if auth and auth.get("type") == "bearer":
        token = os.environ[auth["env_var"]]
        headers["Authorization"] = f"Bearer {token}"

    return MCPClient(
        lambda: streamable_http_client(
            mcp_url,
            http_client=httpx.AsyncClient(
                timeout=httpx.Timeout(300.0, connect=30.0, read=120.0),
                headers=headers,
            ),
        ),
    )
```

### Connection registry

Instead of a global singleton, a dict keyed by MCP URL:

```python
_clients: dict[str, MCPClient] = {}
_lock = threading.Lock()

def get_mcp_client(mcp_url: str, auth: dict | None = None) -> MCPClient:
    """Return a live client, creating/reconnecting as needed."""

def shutdown_all() -> None:
    """Graceful shutdown of all MCP connections."""
```

Multiple agents sharing the same MCP URL reuse one connection. Agents on different MCP servers each get their own.

## Generic MCP Agent (`agents/mcp_agent.py`)

Creates a Strands Agent from a YAML config entry and serves it as an A2A server.

```python
def create_mcp_agent(agent_config: dict) -> Agent:
    """Create an Agent backed by an MCP server."""
    client = get_mcp_client(
        mcp_url=agent_config["mcp_url"],
        auth=agent_config.get("auth"),
    )
    return Agent(
        model=create_model(),
        name=agent_config["name"],
        description=agent_config.get("description", ""),
        system_prompt=agent_config.get("system_prompt", "Use the available tools."),
        tools=[client],
        callback_handler=None,
    )

def serve_mcp_agent(agent_config: dict) -> None:
    """Create and serve an MCP-backed agent as an A2A server."""
    agent = create_mcp_agent(agent_config)
    skills = [AgentSkill(**s) for s in agent_config.get("skills", [])]
    serve_agent(agent, name=agent_config["name"], port=agent_config["port"], skills=skills)
```

### CLI entrypoint

```
python -m agents.mcp_agent --config agents.yaml --agent "Database Reader"
```

Loads the named agent entry from YAML and calls `serve_mcp_agent()`.

## Dynamic Orchestrator

### System prompt

Built dynamically from YAML at agent init time:

```python
def _build_system_prompt(agents_config: list[dict]) -> str:
    agent_descriptions = []
    for cfg in agents_config:
        url = f"http://localhost:{cfg['port']}/"
        desc = cfg.get("description", cfg["name"])
        agent_descriptions.append(
            f'- **{cfg["name"]}** (target_agent_url: "{url}")\n  {desc}'
        )
    return f"""You are the Orchestrator Agent. Route requests to specialist agents.

Available agents:
{chr(10).join(agent_descriptions)}

Use the exact target_agent_url values above with a2a_send_message.
"""
```

### Agent initialisation

```python
def _get_agent() -> Agent:
    agents_config = _load_agents_config()
    known_urls = [f"http://localhost:{cfg['port']}/" for cfg in agents_config]
    provider = A2AClientToolProvider(known_agent_urls=known_urls)
    return Agent(
        model=create_model(),
        system_prompt=_build_system_prompt(agents_config),
        tools=provider.tools,
    )
```

No more hardcoded `database_agent_url` / `graph_agent_url`.

## Dynamic Runner (`run_system.py`)

Reads YAML and spawns agents by type:

- **`mcp`**: `python -m agents.mcp_agent --config agents.yaml --agent "<name>"`
- **`custom`**: `python -m <module>`

Then waits for all agents to be healthy (same health check logic as today), starts the orchestrator.

## Simplified `common/config.py`

Remove per-agent and Neon-specific fields:

```python
class Settings(BaseSettings):
    # Orchestrator
    orchestrator_port: int = 8000
    database_mode: str = "a2a"
    allowed_origins: str = "*"
    api_key: str = ""
    rate_limit: str = "30/minute"
    agents_config: str = "agents.yaml"

    # Gemini Model
    google_api_key: str | None = None
    google_cloud_project: str | None = None
    google_cloud_location: str = "us-central1"
    gemini_model_id: str = "gemini-2.5-flash"

    # Query Store
    store_backend: str = "memory"
    database_url: str | None = None

    # Agent-to-Agent Auth
    agent_api_key: str = ""
```

Neon API key, project ID, etc. are just env vars referenced by `agents.yaml` auth blocks.

## File Changes

### New files
- `agents.yaml` -- agent config
- `mcp_client/client.py` -- generic MCP client factory + registry
- `agents/mcp_agent.py` -- generic MCP agent factory + CLI entrypoint

### Modified files
- `common/server.py` -- bug fix: derive `http_url` from port
- `common/config.py` -- remove per-agent and Neon fields, add `agents_config`
- `agents/orchestrator_agent.py` -- dynamic agent discovery from YAML
- `run_system.py` -- dynamic agent spawning from YAML
- `docker-compose.yml` -- mount `agents.yaml`, simplify env vars
- `.env.example` -- remove Neon-specific vars, add `AGENTS_CONFIG`
- `tests/` -- update imports for deleted modules

### Deleted files
- `mcp_client/neon_mcp.py` -- replaced by `mcp_client/client.py`
- `tools/assistant_factory.py` -- replaced by config-driven MCP agents
- `tools/schema_assistant.py` -- replaced by YAML config
- `tools/insert_assistant.py` -- replaced by YAML config
- `tools/delete_assistant.py` -- replaced by YAML config
- `agents/db_agent.py` -- replaced by `agents/mcp_agent.py` + YAML

### Unchanged files
- `agents/graph_agent.py` -- custom agent, now referenced by YAML
- `agents/model.py` -- shared model factory
- `tools/safety_reviewer.py` -- orchestrator-specific
- `common/schemas.py`, `common/store.py`, `common/log_stream.py`, `common/auth.py`
- `common/task_store.py`, `common/logging_setup.py`, `common/tracing.py`
- Frontend static files

## Out of Scope

- **Direct mode** (`DATABASE_MODE=direct`): Currently loads `db_agent` in-process. With the new architecture, direct mode would need to load MCP tools from YAML config in-process. This can be addressed in a follow-up — the YAML config already has all the information needed.

## Dependencies

Add `pyyaml` to `pyproject.toml` core dependencies.
