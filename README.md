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

- **Safety review** -- Destructive queries (DELETE, DROP, TRUNCATE) are evaluated by an LLM reviewer. Rejected queries get `RECOMMENDED_REJECT` status; approved ones are parked as `PENDING_APPROVAL` for human confirmation.
- **Conversation threads** -- Follow-up replies within a query thread (`POST /query/{id}/reply`).
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

### 4. Make requests

```bash
# Read-only query
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Show me all tables in the database"}'

# Insert
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Insert a new employee named Jane Doe with email jane@example.com"}'

# Delete (triggers safety review + approval flow)
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Delete the employee with id 5"}'

# Approve a pending query
curl -X POST http://localhost:8000/queries/approve/<approval_id>

# Follow-up reply
curl -X POST http://localhost:8000/query/<request_id>/reply \
  -H "Content-Type: application/json" \
  -d '{"query": "How many rows were affected?"}'

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

1. Add the URL to `common/config.py`:
   ```python
   my_agent_url: str = "http://localhost:8003/"
   ```

2. Add the URL to the orchestrator's `known_agent_urls` list and system prompt in `agents/orchestrator_agent.py`.

3. Add a process entry in `run_system.py` (for local dev) and a service in `docker-compose.yml` (for Docker).

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `GET` | `/ready` | Readiness probe (verifies agent initialization) |
| `POST` | `/query` | Submit a query |
| `GET` | `/queries` | List all queries (newest first) |
| `GET` | `/queries/{request_id}` | Get a single query |
| `POST` | `/queries/approve/{approval_id}` | Approve a pending destructive query |
| `POST` | `/queries/reject/{approval_id}` | Reject a pending destructive query |
| `POST` | `/query/{request_id}/reply` | Send a follow-up message |
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
│   ├── schemas.py                    # Pydantic request/response models
│   ├── store.py                      # QueryStore protocol + InMemoryStore
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
│   └── repository.py                 # PostgreSQL QueryStore implementation
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
    ├── test_orchestrator.py          # Query lifecycle tests
    ├── test_store.py                 # InMemoryStore tests
    ├── unit/
    │   └── test_common.py            # Auth, task store, logging tests
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
pytest tests/test_orchestrator.py::test_submit_non_destructive_query

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
