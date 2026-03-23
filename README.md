# A2A Database Orchestrator

Agent-to-Agent (A2A) communication example using the [Strands SDK](https://github.com/strands-agents/sdk-python), implementing a database orchestrator that performs CRUD operations via [Neon MCP](https://neon.tech/).

## Architecture

```
+---------------------+         +---------------------+         +-----------+
| Orchestrator Agent  |  A2A    |   Database Agent     |  MCP    | Neon MCP  |
| (FastAPI :8000)     | <-----> | (A2A Server :8001)   | <-----> | (Remote)  |
+---------------------+         +---------------------+         +-----------+
        ^
        |
   User Requests (REST API)
```

### Orchestrator Agent (port 8000)
- Receives user queries via `POST /query`
- Uses `A2AClientToolProvider` to communicate with the Database Agent over the A2A protocol
- Runs a safety review for destructive queries (DELETE, DROP, etc.) before forwarding

### Database Agent (port 8001)
- Exposed as an A2A server using `strands.multiagent.a2a.A2AServer`
- Connects to the Neon MCP service for actual database operations
- Routes queries to specialist sub-tools:
  - **schema_assistant** -- read-only schema inspection and SELECT queries
  - **insert_assistant** -- INSERT operations
  - **delete_assistant** -- DELETE operations

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

## Run

### Start the full system

```bash
python run_system.py
```

This starts both agents in parallel:
- Database Agent on `http://localhost:8001`
- Orchestrator Agent on `http://localhost:8000`

### Start agents individually

```bash
# Terminal 1: Database Agent
python -m agents.db_agent

# Terminal 2: Orchestrator Agent
python -m agents.orchestrator_agent
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

# Health check
curl http://localhost:8000/health
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
| `POST` | `/query` | Submit a database query |

## Project Structure

```
a2a-strands-example/
├── run_system.py                  # System runner (starts both agents)
├── schemas.py                     # Pydantic request/response models
├── requirements.txt               # Dependencies
├── .env.example                   # Environment variable template
├── agents/
│   ├── model.py                   # Shared Gemini model configuration
│   ├── db_agent.py                # Database Agent (A2A server)
│   └── orchestrator_agent.py      # Orchestrator Agent (FastAPI)
├── mcp_client/
│   └── neon_mcp.py                # Neon MCP client factory
├── tools/
│   ├── assistant_factory.py       # Shared factory for specialist tools
│   ├── schema_assistant.py        # Read-only schema tool
│   ├── insert_assistant.py        # Insert tool
│   ├── delete_assistant.py        # Delete tool
│   └── safety_reviewer.py        # Safety reviewer agent
└── tests/
    ├── conftest.py                # Test fixtures (fully mocked)
    ├── test_smoke.py              # Health check tests
    └── test_orchestrator.py       # Query lifecycle tests
```

## References

- [Strands A2A Inter-Agent Lab](https://github.com/aws-samples/sample-getting-started-with-strands-agents-course/tree/main/course-1/Lab5/strands-a2a-inter-agent) -- A2A communication patterns
- [strands-pos](https://github.com/daniel-was-taken/strands-pos) -- Database orchestration with Neon MCP
