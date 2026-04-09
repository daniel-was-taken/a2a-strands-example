# A2A Multi-Agent System

Multi-agent system using [Strands Agents SDK](https://github.com/strands-agents/sdk-python) and the [A2A protocol](https://github.com/google/a2a-spec). Orchestrator routes queries to specialist agents. Agents are declared in `agents.yaml` -- no code changes needed to add a new MCP-backed agent.

```
User -> Orchestrator (:8000) --A2A--> Database Agent  (:8001, MCP)
             |                   |--> Graph Reviewer  (:8002, custom)
             |                   `--> Research Team   (:8003, custom)
             v
        Frontend (/) + REST API (/conversations/*)
```

`core/` = framework (don't modify) | `agents/` = your agents (fork and customize)

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env              # set GOOGLE_API_KEY + MCP credentials
python run_system.py              # starts orchestrator + all agents
# open http://localhost:8000
```

Direct mode (single process, no A2A): `DATABASE_MODE=direct python run_system.py`

## API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/conversations` | Create conversation |
| `POST` | `/conversations/{id}/messages` | Send message |
| `GET` | `/conversations` | List conversations |
| `GET` | `/conversations/{id}` | Get conversation |
| `DELETE` | `/conversations/{id}` | Delete conversation |
| `POST` | `/conversations/{id}/approve` | Approve destructive query |
| `POST` | `/conversations/{id}/reject` | Reject destructive query |
| `GET` | `/logs/stream` | SSE log stream |
| `GET` | `/health` | Health check |

```bash
curl -X POST http://localhost:8000/conversations
curl -X POST http://localhost:8000/conversations/<id>/messages \
  -H "Content-Type: application/json" \
  -d '{"content": "Show me all tables"}'
```

## Adding Agents

**MCP agent** -- YAML only, no Python:

```yaml
# agents.yaml
- name: My Agent
  type: mcp
  port: 8004
  description: What this agent does
  mcp_url: https://example.com/mcp
  auth:
    type: bearer
    env_var: MY_API_KEY
  system_prompt: You are a specialist for ...
  skills:
    - id: my-skill
      name: My Skill
      description: What this skill does
      tags: [example]
```

**Custom agent** -- Python + YAML:

```python
# agents/my_agent.py
from strands import Agent
from core.model import create_model
from core.server import serve_agent

agent = Agent(model=create_model(), name="My Agent", tools=[...], callback_handler=None)

if __name__ == "__main__":
    serve_agent(agent, name="my-agent", port=8004)
```

```yaml
# agents.yaml
- name: My Agent
  type: custom
  port: 8004
  description: What this agent does
  module: agents.my_agent
  factory: serve
```

Four patterns: **MCP** (YAML-only), **Graph** (`agents/graph_reviewer.py`), **Swarm** (`agents/research_team.py`), **Pipeline** (`examples/pipeline_agent.py`).

## Key Features

- **Safety review** -- destructive queries (DELETE/DROP/TRUNCATE) go through LLM review + human approval
- **Context isolation** -- agent memory reset per turn, rebuilt from conversation history (last 20 messages)
- **Auth** -- `X-API-Key` on orchestrator, `X-Agent-API-Key` for inter-agent calls
- **Persistence** -- in-memory (default) or PostgreSQL (`STORE_BACKEND=postgres`)
- **Observability** -- structured JSON logging, SSE log stream, OpenTelemetry tracing
- **Rate limiting** -- configurable via `RATE_LIMIT`

## Development

```bash
pytest                            # tests (fully mocked, no API keys needed)
ruff check . && ruff format .     # lint + format
mypy core/ agents/ db/            # type check
docker compose up --build         # run with Docker
```

## Deployment

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars  # configure GCP project
./deploy.sh                                                # build, push, terraform apply
./destroy.sh                                               # tear down
```

## Diagrams

- [Architecture](docs/architecture.md) -- system components, data flows, sequence diagrams
- [Use Cases](docs/use-cases.md) -- actor interactions, detailed use case descriptions

## References

[Strands SDK](https://github.com/strands-agents/sdk-python) | [A2A Spec](https://github.com/google/a2a-spec) | [Neon MCP](https://neon.tech/docs/get-started-with-neon/mcp)
