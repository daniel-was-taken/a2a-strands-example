# Extending the A2A Multi-Agent System

This guide explains how to add agents, tools, and customizations to the
A2A multi-agent system. The system is designed around clear extension
points so you can adapt it to different domains without changing the core
framework code.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Adding a New MCP Agent](#adding-a-new-mcp-agent)
3. [Adding a Custom Agent](#adding-a-custom-agent)
4. [Graph Pattern](#graph-pattern)
5. [Swarm Pattern](#swarm-pattern)
6. [Changing the LLM Provider](#changing-the-llm-provider)
7. [Changing the MCP Backend](#changing-the-mcp-backend)
8. [Customizing Safety Rules](#customizing-safety-rules)
9. [Adapting to a Different Domain](#adapting-to-a-different-domain)
10. [Frontend Customization](#frontend-customization)
11. [Production Deployment Notes](#production-deployment-notes)

---

## Architecture Overview

```
                          ┌──────────────────────────────────┐
                          │           Frontend               │
                          │   ChatGPT-style conversation UI  │
                          │   (index.html / style.css / js)  │
                          └────────────┬─────────────────────┘
                                       │ REST (conversations API)
                          ┌────────────▼─────────────────────┐
                          │    Orchestrator Agent (port 8000) │
                          │    FastAPI + Strands Agent        │
                          │                                   │
                          │  • Conversation CRUD              │
                          │  • Safety review + approval flow  │
                          │  • Agent context isolation        │
                          │  • Routes to agents via A2A       │
                          └────────────┬─────────────────────┘
                                       │ A2A Protocol
                          ┌────────────▼─────────────────────┐
                          │    Agents (from agents.yaml)      │
                          │                                   │
                          │  MCP Agents (port 8001+):         │
                          │  • Config-driven (any MCP server) │
                          │                                   │
                          │  Custom Agents:                   │
                          │  • Graph Reviewer (port 8002)     │
                          │  • Research Team  (port 8003)     │
                          └────────────┬─────────────────────┘
                                       │ MCP Protocol
                          ┌────────────▼─────────────────────┐
                          │    MCP Servers                    │
                          │    (Remote or local, any provider)│
                          └──────────────────────────────────┘
```

The codebase has a clear boundary: **`core/`** is the framework (don't modify when forking), **`agents/`** is user agents (fork and customize).

**Key concepts:**

| Concept | What it is | Where it lives |
|---------|-----------|----------------|
| **Agent** | A Strands `Agent` with a system prompt and tools. Exposed as an A2A server via `serve_agent()`. | `agents/` |
| **MCP Agent** | Config-driven agent created from `agents.yaml`. No Python code needed. | `core/server.py` (`create_mcp_agent`) |
| **Custom Agent** | Python-defined agent with a factory function (e.g. Graph Reviewer, Research Team). | `agents/*.py` |
| **Conversation** | A persistent chat thread with messages, events, and approval state. | `core/schemas.py` |
| **ConversationStore** | Protocol for persisting conversations. In-memory by default, swappable to Postgres. | `core/store.py` |
| **MCP Client** | Connects an agent to an external service via Model Context Protocol. | `core/mcp.py` |

---

## Adding a New MCP Agent

The simplest way to add a new agent — no Python code required.

### Step-by-step

**1. Add an entry to `agents.yaml`:**

```yaml
agents:
  - name: Analytics Agent
    type: mcp
    port: 8004
    description: Handles data analysis and reporting queries
    mcp_url: https://your-mcp-server.example.com/mcp
    auth:
      headers:
        Authorization: "Bearer ${ANALYTICS_API_KEY}"
    tools:
      - run_query
      - get_schema
    system_prompt: |
      You are an analytics specialist. Use the available MCP tools
      to answer data analysis questions.
    skills:
      - id: analytics
        name: Analytics
        description: Data analysis and reporting
        tags: [analytics, data]
```

**2. Set the required env var:**

```bash
# In .env
ANALYTICS_API_KEY=your-key-here
```

**3. Run the system:**

```bash
python run_system.py
```

The orchestrator auto-discovers agents from `agents.yaml` and builds its
routing prompt dynamically. No changes to orchestrator code needed.

### agents.yaml reference

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Display name (used in orchestrator routing prompt) |
| `type` | Yes | `mcp` or `custom` |
| `port` | Yes | Port for the A2A server |
| `description` | Yes | What this agent does (used for LLM routing) |
| `mcp_url` | Yes (mcp) | URL of the MCP server |
| `auth` | No | Auth headers with `${ENV_VAR}` references |
| `tools` | No | Allowlist of MCP tool names (all tools if omitted) |
| `system_prompt` | No | Custom system prompt for the agent |
| `skills` | No | A2A skill declarations for the agent card |
| `host` | No | Hostname (default: `localhost`) |

---

## Adding a Custom Agent

For agents that need custom Python logic beyond what MCP provides.

### Step-by-step

**1. Create the agent module** in `agents/`:

```python
# agents/my_agent.py
from strands import Agent
from strands.tools.mcp import MCPClient
from mcp.client.streamable_http import streamable_http_client

from core.model import create_model
from core.server import serve_agent


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
    serve_agent(agent, name="my-agent", port=8004)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    serve()
```

**2. Register in `agents.yaml`:**

```yaml
agents:
  - name: My Agent
    type: custom
    port: 8004
    description: Handles requests for my service
    module: agents.my_agent
    factory: serve
```

**3. Add the process to `run_system.py`:**

```python
def start_my_agent():
    from agents.my_agent import serve
    serve()

# In main():
my_process = multiprocessing.Process(target=start_my_agent, name="my-agent")
my_process.start()
```

**4. Add the service to `docker-compose.yml`:**

```yaml
my-agent:
  build: .
  command: ["python", "-m", "agents.my_agent"]
  env_file: .env
  ports:
    - "8004:8004"
```

---

## Graph Pattern

Use Strands `GraphBuilder` when your agent needs a multi-step workflow with
conditional branching (e.g. analyze → implement → review with retry loops).

See `agents/graph_reviewer.py` for the full example. Key structure:

```python
# agents/graph_reviewer.py
from strands.multiagent.graph import GraphBuilder
from core.model import create_model
from core.server import serve_agent

def create_graph_agent():
    graph = (
        GraphBuilder()
        .add_node("analyze",    analyze_agent)
        .add_node("implement",  implement_agent)
        .add_node("review",     review_agent)
        .add_edge("analyze",    "implement")
        .add_conditional_edge(
            "review",
            lambda result: "implement" if "needs revision" in result else END,
            max_iterations=5,
        )
        .set_entry_point("analyze")
        .build()
    )
    return graph

def serve():
    serve_agent(create_graph_agent(), name="graph-reviewer", port=8002)
```

Register in `agents.yaml` as `type: custom` with `module: agents.graph_reviewer` and `factory: serve`.

Also see `examples/a2a_graph.py` for a standalone demo.

---

## Swarm Pattern

Use the Swarm pattern when you want autonomous agent handoffs — agents
transfer control to each other based on context, without a fixed workflow.

See `agents/research_team.py` for the full example. Key structure:

```python
# agents/research_team.py
from strands.multiagent.swarm import Swarm
from core.model import create_model
from core.server import serve_agent

def create_research_team():
    researcher = Agent(model=create_model(), name="Researcher", ...)
    analyst    = Agent(model=create_model(), name="Analyst", ...)
    writer     = Agent(model=create_model(), name="Writer", ...)

    swarm = Swarm(agents=[researcher, analyst, writer])
    return swarm

def serve():
    serve_agent(create_research_team(), name="research-team", port=8003)
```

Register in `agents.yaml` as `type: custom` with `module: agents.research_team` and `factory: serve`.

Also see `examples/a2a_swarm.py` for a standalone demo.

---

## Changing the LLM Provider

The LLM configuration is centralized in `core/model.py`. All agents call
`create_model()` and receive the same model instance.

### Switching to a different Gemini model

Set the environment variable:

```bash
GEMINI_MODEL_ID=gemini-2.5-pro
```

### Switching to a different provider (e.g. Anthropic)

The Strands SDK supports multiple model providers. Replace the model factory:

```python
# core/model.py
import os
from strands.models.anthropic import AnthropicModel

MODEL_ID = os.environ.get("MODEL_ID", "claude-sonnet-4-20250514")


def create_model() -> AnthropicModel:
    return AnthropicModel(
        client_args={"api_key": os.environ["ANTHROPIC_API_KEY"]},
        model_id=MODEL_ID,
    )
```

Then update `pyproject.toml` dependencies:

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

## Changing the MCP Backend

MCP servers are configured per-agent in `agents.yaml`. To change which MCP
server an agent connects to, update its `mcp_url` and `auth` fields.

### Using a different MCP service

```yaml
agents:
  - name: My DB Agent
    type: mcp
    port: 8001
    description: Database queries via custom MCP server
    mcp_url: https://your-mcp-endpoint.com/mcp
    auth:
      headers:
        Authorization: "Bearer ${YOUR_API_KEY}"
```

### Using a local MCP server (stdio)

For MCP servers that run as subprocesses, create a custom agent that uses
stdio transport:

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

In `core/orchestrator.py`:

```python
DESTRUCTIVE_KEYWORDS = {"delete", "remove", "drop", "truncate", "destroy", "update", "alter"}
```

### Changing the safety review logic

The safety reviewer is in `core/safety.py`. Edit the system prompt
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
or escalate based on query severity. The `ConversationStore` protocol
supports adding custom fields to track approval chains.

---

## Adapting to a Different Domain

The orchestrator pattern is not database-specific. To adapt to a completely
different domain (e.g. customer support, document processing, DevOps):

### 1. Define specialist agents in `agents.yaml`

```yaml
agents:
  - name: Ticket Handler
    type: mcp
    port: 8001
    description: Create and manage support tickets
    mcp_url: https://your-ticketing-mcp.example.com/mcp
    system_prompt: You are a support ticket specialist...

  - name: Knowledge Base
    type: mcp
    port: 8002
    description: Search the company knowledge base
    mcp_url: https://your-kb-mcp.example.com/mcp
    system_prompt: You are a knowledge base search specialist...
```

### 2. Or use `@tool` for non-MCP integrations

Create a custom agent with native Python tools:

```python
from strands import Agent, tool

@tool
def search_knowledge_base(query: str) -> str:
    """Search the company knowledge base."""
    # Call your API here
    return results

agent = Agent(
    model=create_model(),
    tools=[search_knowledge_base],
    system_prompt="You are a support agent...",
)
```

### 3. Update safety rules

Change `DESTRUCTIVE_KEYWORDS` and the safety reviewer prompt to match
the sensitive operations in your domain.

### 4. Update the frontend

- Change the title and placeholder text in `frontend/index.html`
- Adjust the CSS custom properties in `frontend/style.css` for theming
- The conversation API (`/conversations`, `/conversations/{id}/messages`) stays the same

---

## Frontend Customization

The frontend is a ChatGPT-style conversation UI — plain HTML/CSS/JS served
by FastAPI at `/`. No build step required.

| File | Purpose | How to customize |
|------|---------|------------------|
| `frontend/index.html` | Page structure (sidebar + chat area) | Edit HTML directly |
| `frontend/style.css` | All styles | Modify CSS custom properties in `:root` for theming |
| `frontend/app.js` | `ApiClient` class + rendering | Edit API methods or `render*` functions |

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

### Key UI components

- **Sidebar**: Conversation list with "New Chat" button
- **Chat area**: Message thread with user/agent bubbles
- **Approval dialog**: Inline approve/reject buttons when a conversation is `awaiting_approval`
- **Activity log**: Collapsible panel showing agent routing events
- **SSE log panel**: Real-time streaming logs from the orchestrator

---

## Production Deployment Notes

### Docker

```bash
docker compose up --build
```

Services defined in `docker-compose.yml`:
- **orchestrator** on port 8000 (includes the frontend at `/`)
- **database-agent** on port 8001
- **graph-reviewer** on port 8002
- **research-team** on port 8003

### GCP Cloud Run + Terraform

1. Copy `infra/terraform.tfvars.example` to `infra/terraform.tfvars`
2. Create secrets in GCP Secret Manager for env vars
3. Run `./deploy.sh`
4. To tear down: `./destroy.sh`

### Authentication

The system supports optional API key authentication:

- **`X-API-Key`** header on the orchestrator (set `API_KEY` env var)
- **`X-Agent-API-Key`** header for inter-agent A2A calls (set `AGENT_API_KEY` env var)

For stronger auth, add middleware for JWT validation (Firebase Auth, Auth0)
or use GCP IAP in front of Cloud Run.

### Persistent Storage

The in-memory `InMemoryConversationStore` loses data on restart. For production:

- Set `STORE_BACKEND=postgres` and `DATABASE_URL` to use `PostgresConversationStore`
- Or implement the `ConversationStore` protocol with your preferred backend:

```python
class FirestoreStore:
    """Google Cloud Firestore implementation of ConversationStore."""

    def create(self, conversation: Conversation) -> None:
        db.collection("conversations").document(conversation.id).set(
            conversation.model_dump()
        )

    def get(self, conversation_id: str) -> Conversation | None:
        doc = db.collection("conversations").document(conversation_id).get()
        return Conversation(**doc.to_dict()) if doc.exists else None

    # ... implement remaining methods (list_all, add_message, add_event, update, delete)
```

Then register it in `core/store.py`:

```python
def _create_store() -> ConversationStore:
    if settings.store_backend == "firestore":
        return FirestoreStore()
    ...
```

### Rate Limiting

Rate limiting is built in via `slowapi`. Configure via the `RATE_LIMIT` env var
(default: `30/minute`). Applied to all endpoints except health checks and
static files.
