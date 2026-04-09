# A2A Agent Framework

A framework for creating and serving [Agent-to-Agent (A2A)](https://github.com/google/a2a-spec) agents backed by MCP servers, built with the [Strands Agents SDK](https://github.com/strands-agents/sdk-python). Agents are declared in `agents.yaml` and spun up dynamically -- no Python code changes needed to add a new MCP-backed agent.

**LLM:** Google Gemini (configurable via `GEMINI_MODEL_ID`)
**MCP:** Any MCP server (configured per-agent in `agents.yaml`)

## Quick Start

### 1. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure

```bash
cp .env.example .env
```

Set at minimum:

| Variable | Description |
|----------|-------------|
| `GOOGLE_API_KEY` | Google AI Studio API key (for Gemini) |

MCP server credentials (API keys, etc.) are referenced by `agents.yaml` auth blocks and should be set as env vars. See `.env.example` for the full list.

### 3. Run

```bash
python run_system.py
```

This reads `agents.yaml` and starts every declared agent as a separate process. Each agent exposes `/.well-known/agent-card.json` and the standard A2A protocol endpoints.

To start a single agent:

```bash
python -m core.server --config agents.yaml --agent "Database Agent"
```

## Architecture

Each agent is an independent A2A server. There is no central orchestrator -- agents are peers that can be composed by any A2A-compatible client.

```
Agents declared in agents.yaml
├── Database Agent   (MCP, port 8001)  -- Neon MCP
├── Graph Reviewer   (custom, port 8002)  -- multi-step graph workflow
├── Research Team    (custom, port 8003)  -- autonomous swarm
├── DeepWiki Agent   (MCP, port 8004)  -- DeepWiki MCP
└── Kaggle Agent     (MCP, port 8005)  -- Kaggle MCP
```

### Agent Types

**MCP agents** are config-driven. Define a name, MCP server URL, auth, and system prompt in `agents.yaml` -- no Python needed. The framework connects to the MCP server, resolves available tools, builds a Strands Agent, and serves it via A2A.

**Custom agents** are Python modules that create a Strands Agent with any pattern (graph workflows, swarms, pipelines) and serve it using `serve_agent()`.

### Key Features

- **Config-driven MCP agents** -- YAML-only, no code required
- **Custom agent patterns** -- Graph (multi-step workflows with revision loops), Swarm (autonomous agent handoffs)
- **`serve_agent()` helper** -- handles A2A protocol, auth, CORS, structured logging, and tracing for any Strands agent
- **Auto-reconnecting MCP client** -- connection registry with 3-attempt exponential backoff; agents sharing the same MCP URL reuse one connection
- **Inter-agent auth** -- optional `X-Agent-API-Key` header validation (no-op when key is empty; always exempt: `/.well-known/agent-card.json`, `/health`, `/ready`)
- **OpenTelemetry tracing** -- set `OTEL_EXPORTER_OTLP_ENDPOINT` to enable

## Project Structure

```
a2a-strands-example/
├── run_system.py                     # Agent runner (starts all agents)
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── agents.yaml                       # Agent definitions (MCP and custom types)
├── core/                             # Framework
│   ├── config.py                     # Pydantic Settings (all env vars)
│   ├── server.py                     # serve_agent() + MCP agent factory + CLI
│   ├── mcp.py                        # Generic MCP client factory + registry
│   ├── model.py                      # Shared Gemini model factory
│   ├── auth.py                       # X-Agent-API-Key middleware
│   ├── logging.py                    # Structured JSON logging
│   ├── task_store.py                 # In-memory A2A TaskStore
│   └── tracing.py                    # OpenTelemetry setup
├── agents/                           # Example agents
│   ├── graph_reviewer.py             # Graph Agent (analyze -> implement -> review)
│   └── research_team.py              # Swarm Agent (autonomous handoffs)
├── examples/                         # Standalone pattern demos
│   ├── mcp_agent.py                  # Minimal MCP agent
│   ├── a2a_graph.py                  # A2A + graph pattern
│   ├── a2a_swarm.py                  # A2A + swarm pattern
│   └── pipeline_agent.py            # Graph with remote A2AAgent nodes
├── frontend/                         # Reference UI (requires custom backend)
├── infra/                            # Terraform (Cloud Run)
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_core.py              # Auth, task store, logging
    │   ├── test_mcp.py               # MCP client + agent factory
    │   ├── test_server_url.py        # serve_agent URL derivation
    │   └── test_agents_config.py     # YAML config parsing
    └── integration/
        ├── test_a2a_server.py        # A2A protocol
        └── test_agent_card.py        # AgentCard contract
```

## Adding a New Agent

### MCP agent (YAML-only)

Add an entry to `agents.yaml`:

```yaml
agents:
  - name: "My Agent"
    type: mcp
    port: 8006
    description: "What this agent does"
    mcp_url: "https://example.com/mcp"
    auth:
      type: bearer
      env_var: MY_API_KEY
    system_prompt: |
      You are MyAgent, a specialist for ...
    skills:
      - id: my-skill
        name: My Skill
        description: "What this skill does"
        tags: [example]
```

Run it with `python run_system.py` (starts all agents) or individually:

```bash
python -m core.server --config agents.yaml --agent "My Agent"
```

### Custom agent (Python)

Create a module that builds a Strands Agent and serves it with `serve_agent()`:

```python
# agents/my_agent.py
from strands import Agent
from strands.tools.mcp import MCPClient
from mcp.client.streamable_http import streamable_http_client

from core.model import create_model
from core.server import serve_agent


def create_my_agent() -> Agent:
    mcp_client = MCPClient(
        lambda: streamable_http_client("http://localhost:9000/mcp")
    )
    return Agent(
        model=create_model(),
        name="My Agent",
        description="Handles requests for my service",
        system_prompt="You are a specialist agent for ...",
        tools=[mcp_client],
        callback_handler=None,
    )


def serve():
    agent = create_my_agent()
    serve_agent(agent, name="my-agent", port=8006)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    serve()
```

Register it in `agents.yaml`:

```yaml
agents:
  - name: "My Agent"
    type: custom
    port: 8006
    description: "What this agent does"
    module: "agents.my_agent"
    factory: "serve"
```

Four patterns are available: **MCP** (YAML-only), **Graph** (see `agents/graph_reviewer.py`), **Swarm** (see `agents/research_team.py`), and **Pipeline** (see `examples/pipeline_agent.py`).

## Testing

All tests use mocked agents -- no real API keys needed.

```bash
pytest                                # All tests
pytest tests/unit/test_core.py -v     # Single file
pytest -x                             # Stop on first failure
```

## Code Quality

```bash
ruff check .                          # Lint
ruff check --fix .                    # Auto-fix
ruff format .                         # Format
mypy core/ agents/                    # Type check
```

## Docker

```bash
docker compose up --build             # All agents
docker compose up database-agent      # Single agent
```

Each agent runs as a separate container with its own health check against `/.well-known/agent-card.json`.

## Deployment

### Cloud Run + Terraform

1. Copy `infra/terraform.tfvars.example` to `infra/terraform.tfvars` and fill in your GCP project config.
2. Create secrets in GCP Secret Manager for the required environment variables.
3. Run `./deploy.sh`.
4. To tear down: `./destroy.sh`.

## References

- [Strands Agents SDK](https://github.com/strands-agents/sdk-python)
- [Strands A2A Documentation](https://strandsagents.com/latest/user-guide/concepts/multi-agent/a2a/)
- [A2A Protocol Specification](https://github.com/google/a2a-spec)
- [Neon MCP](https://neon.tech/docs/get-started-with-neon/mcp)
