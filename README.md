# A2A Multi-Agent System

A production-ready [Agent-to-Agent (A2A)](https://github.com/google/a2a-spec) multi-agent system built with the [Strands Agents SDK](https://github.com/strands-agents/sdk-python). An orchestrator routes user queries to specialist agents over HTTP using the A2A protocol.

**LLM:** Google Gemini (configurable via `GEMINI_MODEL_ID`)
**MCP:** Any MCP server (configured per-agent in `agents.yaml`)
**Framework:** FastAPI + Strands A2A SDK

## Architecture

```
User -> Orchestrator (FastAPI :8000)
            |
            +-- A2A --> [Agents declared in agents.yaml]
                        ├── MCP Agent (config-driven, any MCP server)
                        └── Custom Agent (Python factory, e.g. Graph Agent)
```

Agents are declared in `agents.yaml` and spun up dynamically — no Python code changes needed to add a new MCP-backed agent. The orchestrator discovers agents via `A2AClientToolProvider` and routes queries based on intent. Each specialist agent runs as an independent A2A server.

### Two Operating Modes

| Mode | Command | Description |
|------|---------|-------------|
| **A2A** (default) | `python run_system.py` | Orchestrator + agents from agents.yaml |
| **Direct** | `DATABASE_MODE=direct python run_system.py` | Single process, first MCP agent in-process |

### Key Features

- **ChatGPT-style conversations** -- Multi-turn chat threads with persistent context. Each conversation is a first-class object with its own message history.
- **Agent context isolation** -- The agent singleton's memory is reset before each turn; context is rebuilt from the conversation's stored messages (last 20). No cross-conversation leakage.
- **Safety review** -- Destructive queries (DELETE, DROP, TRUNCATE) are evaluated by an LLM reviewer. The conversation enters `awaiting_approval` status for human confirmation with inline approve/reject UI.
- **SSE log streaming** -- Real-time agent logs via `GET /logs/stream`.
- **Auth** -- Optional `X-API-Key` header on the orchestrator, optional `X-Agent-API-Key` for inter-agent calls.
- **Rate limiting** -- Configurable via `RATE_LIMIT` (default: `30/minute`).
- **Swappable persistence** -- In-memory (default) or PostgreSQL (`STORE_BACKEND=postgres`).
- **OpenTelemetry tracing** -- Set `OTEL_EXPORTER_OTLP_ENDPOINT` to enable.

## Quick Start

### 1. Create a virtual environment and install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure environment

```bash
cp .env.example .env
```

Required variables:

| Variable | Description |
|----------|-------------|
| `GOOGLE_API_KEY` | Google AI Studio API key (for Gemini) |
| `AGENTS_CONFIG` | Path to agents YAML config (default: `agents.yaml`) |

MCP server credentials (API keys, etc.) are referenced by `agents.yaml` auth blocks and should be set as env vars. See `.env.example` for the full list of optional settings.

### 3. Run

```bash
python run_system.py
```

### 4. Open the UI

Navigate to `http://localhost:8000` in your browser. Click **+ New Chat** to start a conversation.

### 5. API usage (curl)

```bash
# Create a conversation
curl -X POST http://localhost:8000/conversations

# Send a message
curl -X POST http://localhost:8000/conversations/<id>/messages \
  -H "Content-Type: application/json" \
  -d '{"content": "Show me all tables in the database"}'

# Send a destructive query (triggers safety review + approval flow)
curl -X POST http://localhost:8000/conversations/<id>/messages \
  -H "Content-Type: application/json" \
  -d '{"content": "Delete the employee with id 5"}'

# Approve / reject a pending destructive query
curl -X POST http://localhost:8000/conversations/<id>/approve
curl -X POST http://localhost:8000/conversations/<id>/reject

# List conversations
curl http://localhost:8000/conversations

# Health check
curl http://localhost:8000/health
```

## Adding a New Agent

The project is designed so that anyone can add a new A2A agent with minimal boilerplate. The `serve_agent()` helper in `common/server.py` handles all the server infrastructure (logging, tracing, A2A protocol, auth middleware, CORS).

### Minimal example

```python
# agents/my_agent.py
from strands import Agent
from strands.tools.mcp import MCPClient
from mcp.client.streamable_http import streamable_http_client

from agents.model import create_model
from common.server import serve_agent


def create_my_agent() -> Agent:
    """Create an agent that wraps your MCP server."""
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
    serve_agent(agent, name="my-agent", port=8003)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    serve()
```

### Register with the orchestrator

1. Add an entry to `agents.yaml` for auto-discovery:
   ```yaml
   agents:
     - name: My Agent
       type: custom
       port: 8003
       description: Handles requests for my service
       module: agents.my_agent
       factory: serve
   ```

2. Add a process entry in `run_system.py` (for local dev) and a service in `docker-compose.yml` (for Docker).

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `GET` | `/ready` | Readiness probe (verifies agent initialization) |
| `POST` | `/conversations` | Create a new conversation |
| `GET` | `/conversations` | List all conversations (newest first) |
| `GET` | `/conversations/{id}` | Get a conversation with full message history |
| `DELETE` | `/conversations/{id}` | Delete a conversation |
| `POST` | `/conversations/{id}/messages` | Send a message in a conversation |
| `POST` | `/conversations/{id}/approve` | Approve a pending destructive query |
| `POST` | `/conversations/{id}/reject` | Reject a pending destructive query |
| `GET` | `/logs/stream` | SSE log stream |
| `GET` | `/` | Frontend UI |

## Project Structure

```
a2a-strands-example/
├── run_system.py                     # System runner (A2A or direct mode)
├── pyproject.toml                    # Build config, dependencies, tool settings
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── agents.yaml                      # Agent definitions (MCP and custom types)
├── agents/
│   ├── model.py                      # Shared Gemini model factory
│   ├── orchestrator_agent.py         # Orchestrator (FastAPI, routes to agents)
│   ├── mcp_agent.py                  # Generic MCP agent factory + CLI
│   └── graph_agent.py               # Graph Agent (analyze -> implement -> review)
├── common/
│   ├── config.py                     # Pydantic Settings (all env vars)
│   ├── server.py                     # serve_agent() helper for A2A servers
│   ├── schemas.py                    # Pydantic models (Conversation, Message, etc.)
│   ├── store.py                      # ConversationStore protocol + InMemoryStore
│   ├── auth.py                       # X-Agent-API-Key middleware
│   ├── log_stream.py                 # SSE broadcaster
│   ├── logging_setup.py              # Structured JSON logging
│   ├── task_store.py                 # In-memory A2A TaskStore
│   └── tracing.py                    # OpenTelemetry setup
├── tools/
│   └── safety_reviewer.py           # LLM-based safety reviewer
├── mcp_client/
│   └── client.py                     # Generic MCP client factory + registry
├── db/
│   └── repository.py                 # PostgreSQL ConversationStore implementation
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── infra/                            # Terraform (Cloud Run + Artifact Registry)
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   └── terraform.tfvars.example
└── tests/
    ├── conftest.py                   # Shared fixtures (fully mocked)
    ├── test_smoke.py
    ├── test_orchestrator.py          # Conversation lifecycle tests
    ├── test_store.py                 # ConversationStore tests
    ├── unit/
    │   ├── test_common.py            # Auth, task store, logging tests
    │   └── test_schemas.py           # Conversation data model tests
    ├── integration/
    │   ├── test_a2a_server.py        # A2A protocol tests
    │   └── test_agent_card.py        # AgentCard contract tests
    └── e2e/
        └── test_e2e_stub.py          # E2E stubs (requires running system)
```

## Testing

All tests use mocked agents -- no real API keys or database connections needed.

```bash
# Run all tests
pytest

# Run a specific file
pytest tests/test_orchestrator.py -v

# Run a single test
pytest tests/test_orchestrator.py::test_send_message

# Stop on first failure
pytest -x
```

## Code Quality

```bash
# Lint
ruff check .

# Auto-fix lint issues
ruff check --fix .

# Format
ruff format .

# Type checking
mypy agents/ tools/ mcp_client/ common/ db/
```

## Docker

```bash
# Build and run all services
docker compose up --build

# Run a single agent
docker compose up db-agent
```

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
