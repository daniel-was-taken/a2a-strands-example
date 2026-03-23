# Extending the A2A Database Orchestrator

This guide explains how to add agents, tools, and customizations to the
A2A Database Orchestrator. The system is designed around clear extension
points so you can adapt it to different domains without changing the core
framework code.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Adding a New Tool](#adding-a-new-tool)
3. [Adding a New Agent](#adding-a-new-agent)
4. [Changing the LLM Provider](#changing-the-llm-provider)
5. [Changing the Database / MCP Backend](#changing-the-database--mcp-backend)
6. [Customizing Safety Rules](#customizing-safety-rules)
7. [Adapting to a Different Domain](#adapting-to-a-different-domain)
8. [Frontend Customization](#frontend-customization)
9. [Production Deployment Notes](#production-deployment-notes)

---

## Architecture Overview

```
                          ┌──────────────────────────────────┐
                          │           Frontend               │
                          │   (index.html / style.css / js)  │
                          │   Served by FastAPI at /          │
                          └────────────┬─────────────────────┘
                                       │ REST
                          ┌────────────▼─────────────────────┐
                          │    Orchestrator Agent (port 8000) │
                          │    FastAPI + Strands Agent        │
                          │                                   │
                          │  • Receives user queries (REST)   │
                          │  • Runs safety review             │
                          │  • Human-in-the-loop approval     │
                          │  • Forwards to DB Agent via A2A   │
                          └────────────┬─────────────────────┘
                                       │ A2A Protocol
                          ┌────────────▼─────────────────────┐
                          │    Database Agent (port 8001)     │
                          │    Strands Agent + A2A Server     │
                          │                                   │
                          │  Tools:                           │
                          │  • schema_assistant (SELECT only) │
                          │  • insert_assistant (INSERT)      │
                          │  • delete_assistant (DELETE)       │
                          └────────────┬─────────────────────┘
                                       │ MCP Protocol
                          ┌────────────▼─────────────────────┐
                          │    Neon MCP Service               │
                          │    (Remote — mcp.neon.tech)       │
                          │                                   │
                          │  MCP Tools:                       │
                          │  • get_database_tables            │
                          │  • describe_table_schema          │
                          │  • run_sql                        │
                          └──────────────────────────────────┘
```

**Key concepts:**

| Concept    | What it is | Where it lives |
|------------|-----------|----------------|
| **Agent**  | A Strands `Agent` with a system prompt and tools. Can be exposed as an A2A server. | `agents/` |
| **Tool**   | A `@tool`-decorated Python function that an agent can invoke. Created via the factory. | `tools/` |
| **MCP Client** | Connects an agent to an external service (e.g. Neon DB) via Model Context Protocol. | `mcp_client/` |
| **Store**  | In-memory (swappable) persistence for query records and activity events. | `store.py` |

---

## Adding a New Tool

Tools are specialist functions that the Database Agent can route queries to.
Each tool wraps its own Strands Agent + MCP client so it operates independently.

### Step-by-step

**1. Create a new file in `tools/`:**

```python
# tools/update_assistant.py
"""Update operations tool."""

from tools.assistant_factory import SHARED_PROMPT_SUFFIX, create_assistant_tool

UPDATE_SYSTEM_PROMPT = f"""
You are UpdateAssistant, responsible for UPDATE operations on the database.

You may inspect schema details before updating data.
Use the available MCP tools for these tasks:
- get_database_tables: List all tables
- describe_table_schema: Get table schema details
- run_sql: Execute UPDATE statements and follow-up SELECT checks

Only perform update operations or read-only checks needed to support an update.
Do not insert, delete, alter, create, or drop database objects.
{SHARED_PROMPT_SUFFIX}
"""


def create_update_tool(mcp_client_factory):
    return create_assistant_tool(
        tool_name="update_assistant",
        tool_doc="Process and respond to UPDATE requests.",
        system_prompt=UPDATE_SYSTEM_PROMPT,
        query_prefix=(
            "Handle this database update request, "
            "inspecting the target table first if needed: "
        ),
        allowed_ops="Only execute UPDATE statements and read-only verification queries.",
        mcp_client_factory=mcp_client_factory,
    )
```

**2. Register the tool in the Database Agent** (`agents/db_agent.py`):

```python
from tools.update_assistant import create_update_tool

# Inside create_database_agent():
tools=[
    create_schema_tool(create_neon_mcp_client),
    create_insert_tool(create_neon_mcp_client),
    create_delete_tool(create_neon_mcp_client),
    create_update_tool(create_neon_mcp_client),   # ← new
]
```

**3. Update the Database Agent system prompt** to mention the new tool:

```
- update_assistant: for UPDATE operations
```

**4. If the new tool performs destructive operations**, add the relevant
keywords to `DESTRUCTIVE_KEYWORDS` in `agents/orchestrator_agent.py`:

```python
DESTRUCTIVE_KEYWORDS = {"delete", "remove", "drop", "truncate", "destroy", "update"}
```

That's it. The orchestrator discovers tools automatically via A2A.

### Factory parameters reference

| Parameter | Purpose |
|-----------|---------|
| `tool_name` | Function name exposed to the orchestrating agent (must be a valid Python identifier) |
| `tool_doc` | Docstring shown to the LLM for routing decisions |
| `system_prompt` | Governance prompt for the specialist agent |
| `query_prefix` | Instruction prepended to the user's query |
| `allowed_ops` | Short description added to the prompt suffix |
| `mcp_client_factory` | Callable returning a fresh `MCPClient` per invocation |

---

## Adding a New Agent

Agents are independent processes that communicate via A2A protocol.

### Step-by-step

**1. Create the agent module** in `agents/`:

```python
# agents/analytics_agent.py
"""Analytics Agent -- exposed as an A2A server on port 8002."""

import logging
import os

from strands import Agent
from strands.multiagent.a2a import A2AServer

from agents.model import create_model

logger = logging.getLogger(__name__)

ANALYTICS_PORT = int(os.environ.get("ANALYTICS_AGENT_PORT", "8002"))

ANALYTICS_SYSTEM_PROMPT = """
You are AnalyticsAgent, a specialist for data analysis queries.
You generate charts, summaries, and insights from the data.
"""


def create_analytics_agent() -> Agent:
    model = create_model()
    return Agent(
        model=model,
        name="Analytics Agent",
        description="Handles data analysis, charting, and insight generation",
        system_prompt=ANALYTICS_SYSTEM_PROMPT,
        tools=[],  # Add your tools here
    )


def serve():
    logging.basicConfig(level=logging.INFO)
    agent = create_analytics_agent()
    a2a_server = A2AServer(agent=agent, enable_a2a_compliant_streaming=True)
    a2a_server.serve(host="0.0.0.0", port=ANALYTICS_PORT)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    serve()
```

**2. Register the agent URL with the Orchestrator:**

```python
# In agents/orchestrator_agent.py
ANALYTICS_AGENT_URL = os.environ.get("ANALYTICS_AGENT_URL", "http://localhost:8002/")

def _create_orchestrator_agent() -> Agent:
    provider = A2AClientToolProvider(
        known_agent_urls=[DATABASE_AGENT_URL, ANALYTICS_AGENT_URL]
    )
    ...
```

**3. Add the process to `run_system.py`:**

```python
def start_analytics_agent():
    from agents.analytics_agent import serve
    serve()

# In main():
analytics_process = multiprocessing.Process(target=start_analytics_agent, name="analytics-agent")
analytics_process.start()
```

**4. Add the service to `docker-compose.yml`:**

```yaml
analytics-agent:
  build: .
  command: ["python", "-m", "agents.analytics_agent"]
  env_file: .env
  ports:
    - "8002:8002"
```

---

## Changing the LLM Provider

The LLM configuration is centralized in `agents/model.py`. All agents call
`create_model()` and receive the same model instance.

### Switching to a different Gemini model

Set the environment variable:

```bash
GEMINI_MODEL_ID=gemini-2.5-pro
```

### Switching to a different provider (e.g. Anthropic)

The Strands SDK supports multiple model providers. Replace the model factory:

```python
# agents/model.py
import os
from strands.models.anthropic import AnthropicModel

MODEL_ID = os.environ.get("MODEL_ID", "claude-sonnet-4-20250514")


def create_model() -> AnthropicModel:
    return AnthropicModel(
        client_args={"api_key": os.environ["ANTHROPIC_API_KEY"]},
        model_id=MODEL_ID,
    )
```

Then update `requirements.txt`:

```
strands-agents[anthropic]   # instead of [gemini]
```

Because every agent calls `create_model()`, this single change applies
system-wide. You can also create per-agent models if needed.

### Switching to Amazon Bedrock

```python
from strands.models.bedrock import BedrockModel

def create_model() -> BedrockModel:
    return BedrockModel(model_id="us.anthropic.claude-sonnet-4-20250514-v1:0")
```

---

## Changing the Database / MCP Backend

The MCP client is isolated in `mcp_client/neon_mcp.py`. To switch databases:

### Using a different MCP-compatible service

Replace `create_neon_mcp_client()` with a client for your service:

```python
# mcp_client/your_mcp.py
from strands.tools.mcp import MCPClient

def create_your_mcp_client() -> MCPClient:
    return MCPClient(
        lambda: streamable_http_client(
            "https://your-mcp-endpoint.com/mcp",
            http_client=httpx.AsyncClient(
                headers={"Authorization": f"Bearer {os.environ['YOUR_API_KEY']}"},
            ),
        ),
    )
```

Then update the imports in `agents/db_agent.py`:

```python
from mcp_client.your_mcp import create_your_mcp_client

# Replace create_neon_mcp_client with create_your_mcp_client
```

### Using a local MCP server (stdio)

If your MCP server runs as a subprocess (stdio transport):

```python
from strands.tools.mcp import MCPClient
from mcp.client.stdio import stdio_client

def create_local_mcp_client() -> MCPClient:
    return MCPClient(
        lambda: stdio_client(
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "@your-org/mcp-server"],
                env={"DB_URL": os.environ["DATABASE_URL"]},
            ),
        ),
    )
```

---

## Customizing Safety Rules

### Modifying the keyword filter

In `agents/orchestrator_agent.py`:

```python
DESTRUCTIVE_KEYWORDS = {"delete", "remove", "drop", "truncate", "destroy", "update", "alter"}
```

### Changing the safety review logic

The safety reviewer is in `tools/safety_reviewer.py`. Edit the system prompt
to change approval criteria:

```python
SAFETY_REVIEWER_SYSTEM_PROMPT = """
You are SafetyReviewer, responsible for reviewing destructive database requests.

Approve only requests that:
1. Target specific rows with a WHERE clause
2. Affect fewer than 100 rows
3. Include a clear business justification

Reject requests that:
1. Use DELETE/DROP without WHERE
2. Target entire tables
3. Are ambiguous about scope

Output exactly one of:
- APPROVE: <short reason>
- REJECT: <short reason>
"""
```

### Adding multi-level approval

Extend the approval flow in the orchestrator to require multiple reviewers
or escalate based on query severity. The `store.py` `QueryStore` protocol
supports adding custom fields to track approval chains.

---

## Adapting to a Different Domain

The orchestrator pattern is not database-specific. To adapt to a completely
different domain (e.g. customer support, document processing, DevOps):

### 1. Replace the specialist tools

Instead of `schema_assistant` / `insert_assistant` / `delete_assistant`,
create tools for your domain:

```python
# tools/ticket_assistant.py
def create_ticket_tool(mcp_client_factory):
    return create_assistant_tool(
        tool_name="ticket_handler",
        tool_doc="Create and manage support tickets.",
        system_prompt="You are TicketHandler...",
        query_prefix="Handle this support request: ",
        allowed_ops="Create, update, and close tickets.",
        mcp_client_factory=mcp_client_factory,
    )
```

### 2. Replace or remove the MCP client

If your domain doesn't use MCP, create tools directly with `@tool`:

```python
from strands import tool

@tool
def search_knowledge_base(query: str) -> str:
    """Search the company knowledge base."""
    # Call your API here
    return results
```

### 3. Update the agents

- Rewrite `DATABASE_SYSTEM_PROMPT` → your domain-specific routing prompt
- Replace the agent's tools list
- Update `ORCHESTRATOR_SYSTEM_PROMPT` to match the new domain

### 4. Update safety rules

Change `DESTRUCTIVE_KEYWORDS` and the safety reviewer prompt to match
the sensitive operations in your domain.

### 5. Update the frontend

- Change the title and placeholder text in `frontend/index.html`
- Adjust the status badges in `frontend/style.css` if you add new statuses
- Update the API client in `frontend/app.js` if your endpoints change

---

## Frontend Customization

The frontend is plain HTML/CSS/JS served by FastAPI at `/`. No build step required.

| File | Purpose | How to customize |
|------|---------|------------------|
| `frontend/index.html` | Page structure | Edit HTML directly |
| `frontend/style.css` | All styles | Modify CSS custom properties in `:root` for theming |
| `frontend/app.js` | API client + rendering | Edit the `ApiClient` class to change endpoints; edit `render*` functions for UI |

### Theming

Change the CSS custom properties in `frontend/style.css`:

```css
:root {
  --primary: #4f46e5;       /* Main brand color */
  --primary-hover: #4338ca;
  --bg: #f9fafb;            /* Page background */
  --white: #ffffff;          /* Card background */
  --border: #e5e7eb;
  /* ... */
}
```

### Connecting to a different backend

Change the base URL in `frontend/app.js`:

```javascript
const api = new ApiClient("https://your-api.example.com");
```

### Adding new pages

Since there's no router, add new sections directly in `index.html` and
toggle visibility via JS. Or serve multiple HTML files from the `frontend/` directory.

---

## Production Deployment Notes

### Docker

```bash
docker compose up --build
```

Services:
- **orchestrator** on port 8000 (includes the frontend at `/`)
- **db-agent** on port 8001

### GCP Cloud Run

Each agent can be deployed as a separate Cloud Run service:

```bash
# Build and push
gcloud builds submit --tag gcr.io/PROJECT/orchestrator .
gcloud builds submit --tag gcr.io/PROJECT/db-agent .

# Deploy
gcloud run deploy orchestrator \
  --image gcr.io/PROJECT/orchestrator \
  --command python --args "-m,agents.orchestrator_agent" \
  --set-env-vars DATABASE_AGENT_URL=https://db-agent-xxxxx.run.app/

gcloud run deploy db-agent \
  --image gcr.io/PROJECT/db-agent \
  --command python --args "-m,agents.db_agent"
```

### Adding Authentication

The system does not include authentication by default. Options:

1. **GCP IAP** (Identity-Aware Proxy) — adds Google SSO in front of Cloud Run
2. **API Key header** — add `X-API-Key` validation middleware to FastAPI
3. **Firebase Auth / Auth0** — JWT validation middleware
4. **OAuth2** — use FastAPI's built-in OAuth2 support

### Persistent Storage

The in-memory `InMemoryStore` in `store.py` loses data on restart. For production,
implement the `QueryStore` protocol with a persistent backend:

```python
class FirestoreStore:
    """Google Cloud Firestore implementation of QueryStore."""

    def save(self, record: QueryResponse) -> None:
        db.collection("queries").document(record.request_id).set(record.model_dump())

    def get(self, request_id: str) -> QueryResponse | None:
        doc = db.collection("queries").document(request_id).get()
        return QueryResponse(**doc.to_dict()) if doc.exists else None

    # ... implement remaining methods
```

Then swap the singleton in `store.py`:

```python
query_store = FirestoreStore()  # instead of InMemoryStore()
```

### Rate Limiting

Add `slowapi` to protect the `/query` endpoint:

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/query")
@limiter.limit("10/minute")
def submit_query(request: Request, payload: QueryRequest):
    ...
```
