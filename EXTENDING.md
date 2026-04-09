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
8. [Adapting to a Different Domain](#adapting-to-a-different-domain)
9. [Production Deployment Notes](#production-deployment-notes)

---

## Architecture Overview

```
                          ┌──────────────────────────────────┐
                          │    Agents (from agents.yaml)      │
                          │                                   │
                          │  MCP Agents (config-driven):      │
                          │  • Any MCP server, no code needed │
                          │                                   │
                          │  Graph Agents (multi-step):       │
                          │  • GraphBuilder workflows         │
                          │                                   │
                          │  Swarm Agents (autonomous):       │
                          │  • Agent-to-agent handoffs        │
                          └────────────┬─────────────────────┘
                                       │ MCP Protocol
                          ┌────────────▼─────────────────────┐
                          │    MCP Servers                    │
                          │    (Remote or local, any provider)│
                          └──────────────────────────────────┘
```

Each agent is an independent A2A server. There is no central orchestrator
-- agents are started individually or together via `run_system.py`, and
communicate with each other (or with external clients) over the A2A protocol.

The codebase has a clear boundary: **`core/`** is the framework (don't modify when forking), **`agents/`** is user agents (fork and customize).

**Key concepts:**

| Concept | What it is | Where it lives |
|---------|-----------|----------------|
| **Agent** | A Strands `Agent` exposed as an A2A server via `serve_agent()`. | `agents/` |
| **MCP Agent** | Config-driven agent created from `agents.yaml`. No Python code needed. | `core/server.py` |
| **Custom Agent** | Python-defined agent with a factory function (e.g. Graph Reviewer, Research Team). | `agents/*.py` |
| **MCP Client** | Connects an agent to an external service via Model Context Protocol. | `core/mcp.py` |

---

## Adding a New MCP Agent

The simplest way to add a new agent -- no Python code required.

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

`run_system.py` reads `agents.yaml` and starts all declared agents
automatically. No code changes needed.

### agents.yaml reference

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Display name for the agent |
| `type` | Yes | `mcp` or `custom` |
| `port` | Yes | Port for the A2A server |
| `description` | Yes | What this agent does |
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

`run_system.py` reads `agents.yaml` and starts custom agents automatically
using `python -m <module>`.

**3. Add the service to `docker-compose.yml`:**

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
conditional branching (e.g. analyze -> implement -> review with retry loops).

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

Use the Swarm pattern when you want autonomous agent handoffs -- agents
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

## Adapting to a Different Domain

The agent pattern is not database-specific. To adapt to a completely
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

---

## Production Deployment Notes

### Docker

```bash
docker compose up --build
```

Services defined in `docker-compose.yml`:
- **database-agent** on port 8001
- **graph-reviewer** on port 8002
- **research-team** on port 8003

### GCP Cloud Run + Terraform

1. Copy `infra/terraform.tfvars.example` to `infra/terraform.tfvars`
2. Create secrets in GCP Secret Manager for env vars
3. Run `./deploy.sh`
4. To tear down: `./destroy.sh`

### Authentication

Agent-to-agent communication is protected by the **`X-Agent-API-Key`** header
(set the `AGENT_API_KEY` env var). The `AgentAuthMiddleware` in `core/auth.py`
validates this key on all requests except `/.well-known/agent-card.json`,
`/health`, and `/ready`. When the key is empty, authentication is disabled.

For stronger auth, add middleware for JWT validation (Firebase Auth, Auth0)
or use GCP IAP in front of Cloud Run.
