# A2A Database Orchestrator

Agent-to-Agent (A2A) communication example using the [Strands SDK](https://github.com/strands-agents/sdk-python), implementing a database orchestrator that performs CRUD operations via [Neon MCP](https://neon.tech/).

## Architecture

By default the orchestrator runs as a **single service** (direct mode) where the database agent tools are loaded in-process. Set `DATABASE_MODE=a2a` to use the original two-service A2A topology.

### Direct mode (default)

```
+---------------------+         +-----------+
| Orchestrator        |  MCP    | Neon MCP  |
| (FastAPI :8000)     | <-----> | (Remote)  |
+---------------------+         +-----------+
        ^
        |
   User Requests (REST API + SSE)
```

### A2A mode (`DATABASE_MODE=a2a`)

```
+---------------------+         +---------------------+         +-----------+
| Orchestrator Agent  |  A2A    |   Database Agent     |  MCP    | Neon MCP  |
| (FastAPI :8000)     | <-----> | (A2A Server :8001)   | <-----> | (Remote)  |
+---------------------+         +---------------------+         +-----------+
```

### Key features

- **Safety review** — destructive queries (DELETE, DROP, etc.) are evaluated by an LLM safety reviewer. Rejected queries receive `RECOMMENDED_REJECT` status; approved queries are parked as `PENDING_APPROVAL` for human confirmation.
- **Approval flow** — each pending query gets a short `approval_id` for approve/reject actions.
- **SSE log streaming** — real-time agent logs via `GET /logs/stream`.
- **API key auth** — optional `x-api-key` header enforcement (set `API_KEY` env var).
- **Rate limiting** — configurable via `RATE_LIMIT` (slowapi).
- **Swappable persistence** — in-memory (default) or PostgreSQL (`STORE_BACKEND=postgres`).
- **Lifecycle hooks** — Strands `HookProvider` for before/after invocation logging.
- **Cloud Run + Terraform** — deploy via `./deploy.sh`, tear down via `./destroy.sh`.

## Setup

### 1. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Set these values in `.env`:

| Variable | Description |
|---|---|
| `NEON_API_KEY` | Neon API key |
| `NEON_PROJECT_ID` | Neon project ID |
| `NEON_DATABASE` | Neon database name |
| `NEON_BRANCH_ID` | Neon branch ID |
| `GOOGLE_API_KEY` | Google AI Studio API key (for Gemini model) |
| `DATABASE_MODE` | `direct` (default) or `a2a` |
| `API_KEY` | Optional API key for authentication |
| `STORE_BACKEND` | `memory` (default) or `postgres` |
| `DATABASE_URL` | PostgreSQL connection string (when `STORE_BACKEND=postgres`) |

## Run

### Start the system (direct mode — default)

```bash
python run_system.py
```

### Start in A2A mode

```bash
DATABASE_MODE=a2a python run_system.py
```

### Start the orchestrator only

```bash
python -m agents.orchestrator_agent
```

### Docker Compose

```bash
docker compose up --build
```

### Make requests

```bash
# Read-only query
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Show me all tables in the database"}'

# Insert
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Insert a new employee named Jane Doe with email jane@example.com"}'

# Delete (triggers safety review)
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Delete the employee with id 5"}'

# Approve a pending query (use approval_id from response)
curl -X POST http://localhost:8000/queries/approve/<approval_id>

# Health / readiness
curl http://localhost:8000/health
curl http://localhost:8000/ready

# SSE log stream
curl -N http://localhost:8000/logs/stream
```

## Tests

All tests use mocked agents -- no real database or LLM calls.

```bash
pytest tests/ -v
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `GET` | `/ready` | Readiness probe (verifies agent can start) |
| `POST` | `/query` | Submit a database query |
| `GET` | `/queries` | List all queries (newest first) |
| `GET` | `/queries/{request_id}` | Get a single query |
| `POST` | `/queries/approve/{approval_id}` | Approve a pending query |
| `POST` | `/queries/reject/{approval_id}` | Reject a pending query |
| `GET` | `/logs/stream` | SSE log stream |
| `GET` | `/` | Frontend UI |

## Project Structure

```
a2a-strands-example/
├── run_system.py                  # System runner (direct or A2A mode)
├── schemas.py                     # Pydantic request/response models
├── store.py                       # QueryStore protocol + InMemoryStore
├── log_stream.py                  # SSE broadcaster + logging handler
├── hooks.py                       # Strands lifecycle hooks
├── requirements.txt               # Dev dependencies (includes prod)
├── requirements-prod.txt          # Production dependencies
├── Dockerfile                     # Container image
├── docker-compose.yml             # Local multi-service setup
├── deploy.sh                      # Cloud Run deploy script
├── destroy.sh                     # Cloud Run teardown script
├── .env.example                   # Environment variable template
├── agents/
│   ├── model.py                   # Shared Gemini model configuration
│   ├── db_agent.py                # Database Agent (direct tools + A2A server)
│   └── orchestrator_agent.py      # Orchestrator Agent (FastAPI)
├── db/
│   └── repository.py              # PostgreSQL QueryStore implementation
├── mcp_client/
│   └── neon_mcp.py                # Neon MCP client factory
├── tools/
│   ├── assistant_factory.py       # Shared factory for specialist tools
│   ├── schema_assistant.py        # Read-only schema tool
│   ├── insert_assistant.py        # Insert tool
│   ├── delete_assistant.py        # Delete tool
│   └── safety_reviewer.py         # Safety reviewer agent
├── infra/                         # Terraform (Cloud Run + Artifact Registry)
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── terraform.tfvars.example
│   └── modules/
│       ├── artifact-registry/
│       └── cloudrun-runtime/
├── frontend/
│   ├── index.html                 # Frontend UI
│   ├── style.css                  # Styles (includes SSE log panel)
│   └── app.js                     # Vanilla JS client
└── tests/
    ├── conftest.py                # Test fixtures (fully mocked)
    ├── test_smoke.py              # Health check tests
    ├── test_orchestrator.py       # Query lifecycle tests
    └── test_store.py              # InMemoryStore unit tests
```

## Deployment

### Cloud Run + Terraform

1. Copy `infra/terraform.tfvars.example` to `infra/terraform.tfvars` and fill in your GCP project config
2. Create secrets in GCP Secret Manager for each entry in the `secrets` map
3. Run `./deploy.sh`

To tear down: `./destroy.sh`

## Extending

### Future improvements documented in the plan:

- **AgentCore deployment** — Use `BedrockAgentCoreApp` from the [AWS Strands Course](https://github.com/aws-samples/sample-getting-started-with-strands-agents-course/tree/main/course-4) for managed agent hosting
- **Session management** — Add `FileSessionManager` or `SummarizingConversationManager` from Strands for multi-turn conversations
- **Observability** — Integrate LangFuse + RAGAS for evaluation and monitoring (Course 1 Lab 6 pattern)

## References

- [Strands A2A Inter-Agent Lab](https://github.com/aws-samples/sample-getting-started-with-strands-agents-course/tree/main/course-1/Lab5/strands-a2a-inter-agent) -- A2A communication patterns
- [strands-pos](https://github.com/daniel-was-taken/strands-pos) -- Database orchestration with Neon MCP
