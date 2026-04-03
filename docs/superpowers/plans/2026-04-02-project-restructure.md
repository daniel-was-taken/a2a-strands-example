# Project Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure into `core/` (framework) and `agents/` (user-customizable), merge redundant packages, consolidate 3 DB agents into 1, add Swarm demo, provide examples for all 4 agent patterns.

**Architecture:** `common/`, `mcp_client/`, `tools/`, and framework files from `agents/` merge into a single `core/` package. User-facing agents stay in `agents/`. The orchestrator moves to `core/` since it's framework code.

**Tech Stack:** Python 3.11+, Strands Agents SDK, FastAPI, Pydantic v2

**Spec:** `docs/superpowers/specs/2026-04-02-project-restructure-design.md`

---

### Task 1: Create `core/` package with pure renames

Move files that require no logic changes — only the module path changes. This is the foundation everything else builds on.

**Files:**
- Create: `core/__init__.py`
- Create: `core/config.py` (from `common/config.py`)
- Create: `core/schemas.py` (from `common/schemas.py`)
- Create: `core/store.py` (from `common/store.py`)
- Create: `core/auth.py` (from `common/auth.py`)
- Create: `core/log_stream.py` (from `common/log_stream.py`)
- Create: `core/logging.py` (from `common/logging_setup.py`)
- Create: `core/task_store.py` (from `common/task_store.py`)
- Create: `core/tracing.py` (from `common/tracing.py`)
- Create: `core/model.py` (from `agents/model.py`)
- Create: `core/mcp.py` (from `mcp_client/client.py`)
- Create: `core/safety.py` (from `tools/safety_reviewer.py`)

- [ ] **Step 1: Create `core/` directory and `__init__.py`**

```bash
mkdir -p core
touch core/__init__.py
```

- [ ] **Step 2: Copy files into `core/` with new names**

```bash
cp common/config.py core/config.py
cp common/schemas.py core/schemas.py
cp common/store.py core/store.py
cp common/auth.py core/auth.py
cp common/log_stream.py core/log_stream.py
cp common/logging_setup.py core/logging.py
cp common/task_store.py core/task_store.py
cp common/tracing.py core/tracing.py
cp agents/model.py core/model.py
cp mcp_client/client.py core/mcp.py
cp tools/safety_reviewer.py core/safety.py
```

- [ ] **Step 3: Update internal imports in `core/store.py`**

Change:
```python
from common.schemas import ActivityEvent, Conversation, ConversationStatus, Message
```
To:
```python
from core.schemas import ActivityEvent, Conversation, ConversationStatus, Message
```

And change:
```python
from common.config import settings
```
To:
```python
from core.config import settings
```

- [ ] **Step 4: Update internal imports in `core/safety.py`**

Change:
```python
from agents.model import create_model
```
To:
```python
from core.model import create_model
```

- [ ] **Step 5: Update internal imports in `core/model.py`**

Change:
```python
from common.config import settings
```
To:
```python
from core.config import settings
```

- [ ] **Step 6: Update internal imports in `core/logging.py`**

No internal cross-references — file uses only stdlib `logging` and `json`. No changes needed.

- [ ] **Step 7: Update internal imports in `core/tracing.py`**

No internal cross-references — file uses only `opentelemetry` and `logging`. No changes needed.

- [ ] **Step 8: Verify `core/` imports work**

```bash
python -c "from core.config import settings; print(settings.orchestrator_port)"
python -c "from core.schemas import Conversation; print('OK')"
python -c "from core.model import create_model; print('OK')"
```

Expected: `8000`, `OK`, `OK`

- [ ] **Step 9: Commit**

```bash
git add core/
git commit -m "feat: create core/ package with renamed framework modules"
```

---

### Task 2: Move `core/server.py` and merge `mcp_agent.py` into it

The current `common/server.py` has `serve_agent()`. The current `agents/mcp_agent.py` has `load_agents_config()`, `create_mcp_agent()`, and `serve_mcp_agent()`. Merge them all into `core/server.py`.

**Files:**
- Create: `core/server.py` (merge of `common/server.py` + `agents/mcp_agent.py`)

- [ ] **Step 1: Write `core/server.py`**

```python
"""Shared helpers to start any Strands agent as an A2A server.

Includes:
- serve_agent(): wraps an Agent, Graph, or Swarm as an A2A server
- load_agents_config(): reads agents.yaml
- create_mcp_agent(): builds a Strands Agent from an agents.yaml MCP entry
- serve_mcp_agent(): creates and serves an MCP agent

Usage::

    from core.server import serve_agent

    agent = Agent(model=model, system_prompt="...", tools=[...])
    serve_agent(agent, name="my-agent", port=8003)
"""

from __future__ import annotations

import argparse
import logging

import uvicorn
import yaml
from a2a.types import AgentSkill
from fastapi.middleware.cors import CORSMiddleware
from strands import Agent
from strands.multiagent.a2a import A2AServer

from core.auth import AgentAuthMiddleware
from core.config import settings
from core.logging import configure_logging
from core.mcp import create_mcp_client
from core.model import create_model
from core.task_store import InMemoryA2ATaskStore
from core.tracing import configure_tracing

logger = logging.getLogger(__name__)


def load_agents_config(config_path: str = "agents.yaml") -> list[dict]:
    """Load the agents list from a YAML config file."""
    with open(config_path) as f:
        return yaml.safe_load(f)["agents"]


def create_mcp_agent(agent_config: dict) -> Agent:
    """Create a Strands Agent backed by an MCP server.

    Args:
        agent_config: A single agent entry from agents.yaml.
    """
    client = create_mcp_client(
        mcp_url=agent_config["mcp_url"],
        auth=agent_config.get("auth"),
    )
    model = create_model()
    return Agent(
        model=model,
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
    serve_agent(
        agent,
        name=agent_config["name"],
        port=agent_config["port"],
        skills=skills,
    )


def serve_agent(
    agent,
    *,
    name: str,
    port: int,
    http_url: str | None = None,
    skills: list | None = None,
    version: str = "1.0.0",
) -> None:
    """Start a Strands agent as an A2A server with auth, CORS, and structured logging.

    Args:
        agent: A Strands Agent, Graph, or Swarm instance.
        name: Display name used in logs and AgentCard.
        port: TCP port to bind.
        http_url: Public URL advertised in the AgentCard (optional).
        skills: List of AgentSkill entries for the AgentCard.
        version: Semver version for the AgentCard.
    """
    configure_logging(agent_name=name)
    configure_tracing(service_name=name)

    a2a_server = A2AServer(
        agent=agent,
        http_url=http_url or f"http://127.0.0.1:{port}/",
        version=version,
        skills=skills or [],
        task_store=InMemoryA2ATaskStore(),
        enable_a2a_compliant_streaming=True,
    )

    app = a2a_server.to_fastapi_app()
    app.add_middleware(AgentAuthMiddleware, api_key=settings.agent_api_key)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins.split(","),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(description="Run an MCP-backed A2A agent")
    parser.add_argument("--config", default="agents.yaml", help="Path to agents.yaml")
    parser.add_argument("--agent", required=True, help="Agent name from config")
    args = parser.parse_args()

    agents = load_agents_config(args.config)
    agent_cfg = next((a for a in agents if a["name"] == args.agent), None)
    if agent_cfg is None:
        raise SystemExit(f"Agent '{args.agent}' not found in {args.config}")
    if agent_cfg["type"] != "mcp":
        raise SystemExit(f"Agent '{args.agent}' is type '{agent_cfg['type']}', not 'mcp'")

    serve_mcp_agent(agent_cfg)
```

- [ ] **Step 2: Verify imports work**

```bash
python -c "from core.server import serve_agent, load_agents_config, create_mcp_agent; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add core/server.py
git commit -m "feat: merge serve_agent + MCP agent helpers into core/server.py"
```

---

### Task 3: Move orchestrator to `core/orchestrator.py`

Copy `agents/orchestrator_agent.py` to `core/orchestrator.py` and update all imports from `common.*`/`agents.*`/`tools.*` to `core.*`.

**Files:**
- Create: `core/orchestrator.py` (from `agents/orchestrator_agent.py`)

- [ ] **Step 1: Copy the file**

```bash
cp agents/orchestrator_agent.py core/orchestrator.py
```

- [ ] **Step 2: Update all imports in `core/orchestrator.py`**

Replace:
```python
from agents.model import create_model
from common.config import settings
from common.log_stream import broadcaster
from common.log_stream import install as install_sse_handler
from common.schemas import (
    ActivityEvent,
    Conversation,
    ConversationStatus,
    ConversationSummary,
    ErrorResponse,
    HealthResponse,
    Message,
    MessageRequest,
)
from common.store import conversation_store
from tools.safety_reviewer import create_safety_reviewer, review_delete_request
```

With:
```python
from core.config import settings
from core.log_stream import broadcaster
from core.log_stream import install as install_sse_handler
from core.model import create_model
from core.schemas import (
    ActivityEvent,
    Conversation,
    ConversationStatus,
    ConversationSummary,
    ErrorResponse,
    HealthResponse,
    Message,
    MessageRequest,
)
from core.safety import create_safety_reviewer, review_delete_request
from core.store import conversation_store
```

- [ ] **Step 3: Update the lazy agent loader imports**

In `_get_agent()`, replace:
```python
from strands_tools.a2a_client import A2AClientToolProvider
```
(this stays the same — it's an external import)

Replace:
```python
from agents.mcp_agent import create_mcp_agent, load_agents_config
```
With:
```python
from core.server import create_mcp_agent, load_agents_config
```

- [ ] **Step 4: Update `_load_agents_config()` helper**

Replace:
```python
def _load_agents_config() -> list[dict]:
    """Load agents list from the YAML config file."""
    from agents.mcp_agent import load_agents_config

    return load_agents_config(settings.agents_config)
```

With:
```python
def _load_agents_config() -> list[dict]:
    """Load agents list from the YAML config file."""
    from core.server import load_agents_config

    return load_agents_config(settings.agents_config)
```

- [ ] **Step 5: Verify orchestrator imports work**

```bash
python -c "from core.orchestrator import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add core/orchestrator.py
git commit -m "feat: move orchestrator to core/ with updated imports"
```

---

### Task 4: Rewrite `agents/` — graph_reviewer.py and research_team.py

Replace the old `agents/` files with the two demo agents. The MCP database agent needs no Python file — it's config-only.

**Files:**
- Create: `agents/graph_reviewer.py` (rewrite of `agents/graph_agent.py`)
- Create: `agents/research_team.py` (new — Swarm demo)
- Modify: `agents/__init__.py`

- [ ] **Step 1: Write `agents/__init__.py`**

```python
```

(Empty file — just a package marker, same as before.)

- [ ] **Step 2: Write `agents/graph_reviewer.py`**

```python
"""Graph Reviewer — multi-step reasoning workflow exposed as an A2A server.

Workflow: analyze → implement → review, with conditional loops back to
implement if the reviewer says "needs revision" (max 5 iterations).

Registered in agents.yaml as type: custom.
"""

import logging

from a2a.types import AgentSkill
from google import genai
from strands import Agent
from strands.models.gemini import GeminiModel
from strands.multiagent import GraphBuilder
from strands.multiagent.graph import Graph
from strands.types.tools import ToolSpec

from core.model import create_model

logger = logging.getLogger(__name__)

_SKILLS = [
    AgentSkill(
        id="multi-step-reasoning",
        name="Multi-Step Reasoning",
        description=(
            "Analyze, implement, and review solutions through a structured "
            "graph workflow with automatic revision cycles"
        ),
        tags=["reasoning", "analysis", "implementation", "review"],
    ),
]


class NoToolsGeminiModel(GeminiModel):
    """GeminiModel that omits the tools field when there are no tool specs.

    Works around a Gemini API bug where an empty Tool(function_declarations=[])
    causes a 400 error.
    """

    def _format_request_tools(self, tool_specs: list[ToolSpec] | None) -> list[genai.types.Tool]:
        if not tool_specs and not self.config.get("gemini_tools"):
            return []
        return super()._format_request_tools(tool_specs)


def _create_no_tools_model() -> NoToolsGeminiModel:
    """Create a Gemini model that won't send empty tool definitions."""
    base = create_model()
    return NoToolsGeminiModel(
        client_args=base.client_args,
        model_id=base.config["model_id"],
    )


def create_agent() -> Graph:
    """Build a graph-based agent with analyze → implement → review workflow."""
    model = _create_no_tools_model()

    analyzer = Agent(
        model=model,
        name="analyzer",
        system_prompt="Analyze the input. Break down the problem and identify key requirements.",
        tools=[],
        load_tools_from_directory=False,
        callback_handler=None,
    )
    implementer = Agent(
        model=model,
        name="implementer",
        system_prompt="Implement the solution based on the analysis provided.",
        tools=[],
        load_tools_from_directory=False,
        callback_handler=None,
    )
    reviewer = Agent(
        model=model,
        name="reviewer",
        system_prompt=(
            "Review the implementation. If it needs revision, say 'needs revision' and explain why."
        ),
        tools=[],
        load_tools_from_directory=False,
        callback_handler=None,
    )

    builder = GraphBuilder()
    builder.add_node(analyzer, "analyze")
    builder.add_node(implementer, "implement")
    builder.add_node(reviewer, "review")
    builder.add_edge("analyze", "implement")
    builder.add_edge("implement", "review")
    builder.add_edge(
        "review",
        "implement",
        condition=lambda state: "needs revision" in str(state.results.get("review", "")).lower(),
    )
    builder.set_entry_point("analyze")
    builder.set_max_node_executions(5)
    graph = builder.build()
    graph.name = "Graph Reviewer"  # type: ignore[attr-defined]
    graph.description = (  # type: ignore[attr-defined]
        "Handles multi-step reasoning workflows with analyze, implement, and review stages"
    )
    return graph


def serve() -> None:
    """Start the Graph Reviewer as an A2A server."""
    from core.server import serve_agent

    agent = create_agent()
    serve_agent(
        agent,
        name="Graph Reviewer",
        port=8002,
        skills=_SKILLS,
    )


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    serve()
```

- [ ] **Step 3: Write `agents/research_team.py`**

```python
"""Research Team — autonomous swarm agent exposed as an A2A server.

A self-organizing team of researcher, writer, and editor agents that
collaborate via handoffs. The swarm decides autonomously which agent
should handle each part of the task.

Registered in agents.yaml as type: custom.
"""

import logging

from a2a.types import AgentSkill
from strands import Agent
from strands.multiagent import Swarm

from core.model import create_model

logger = logging.getLogger(__name__)

_SKILLS = [
    AgentSkill(
        id="collaborative-research",
        name="Collaborative Research",
        description="Multi-agent research, writing, and editing with autonomous handoffs",
        tags=["research", "writing", "collaboration"],
    ),
]


def create_agent() -> Swarm:
    """Build a swarm with researcher, writer, and editor agents."""
    model = create_model()

    researcher = Agent(
        model=model,
        name="researcher",
        system_prompt=(
            "You are a research specialist. Gather information, facts, and analysis.\n"
            "When you have enough material, hand off to the 'writer' agent."
        ),
        description="Researches topics and gathers information",
        callback_handler=None,
    )
    writer = Agent(
        model=model,
        name="writer",
        system_prompt=(
            "You are a technical writer. Create clear, well-structured content "
            "from the research provided.\n"
            "When the draft is ready, hand off to the 'editor' agent.\n"
            "If you need more research, hand off to the 'researcher' agent."
        ),
        description="Writes clear content from research",
        callback_handler=None,
    )
    editor = Agent(
        model=model,
        name="editor",
        system_prompt=(
            "You are an editor. Polish the content for clarity, accuracy, and style.\n"
            "If there are major issues, hand back to the 'writer' agent.\n"
            "If the content is good, produce the final version and stop."
        ),
        description="Edits and polishes written content",
        callback_handler=None,
    )

    swarm = Swarm(
        [researcher, writer, editor],
        entry_point=researcher,
        max_handoffs=10,
        max_iterations=15,
        execution_timeout=300.0,
    )
    swarm.name = "Research Team"  # type: ignore[attr-defined]
    swarm.description = (  # type: ignore[attr-defined]
        "Collaborative research team with autonomous handoffs between agents"
    )
    return swarm


def serve() -> None:
    """Start the Research Team as an A2A server."""
    from core.server import serve_agent

    agent = create_agent()
    serve_agent(
        agent,
        name="Research Team",
        port=8003,
        skills=_SKILLS,
    )


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    serve()
```

- [ ] **Step 4: Verify agent imports work**

```bash
python -c "from agents.graph_reviewer import create_agent; print('OK')"
python -c "from agents.research_team import create_agent; print('OK')"
```

Expected: `OK`, `OK`

- [ ] **Step 5: Commit**

```bash
git add agents/__init__.py agents/graph_reviewer.py agents/research_team.py
git commit -m "feat: add graph_reviewer and research_team demo agents"
```

---

### Task 5: Update `agents.yaml`, `run_system.py`, and Docker files

Update the system configuration to use the new `core/` module paths and 3-agent setup.

**Files:**
- Modify: `agents.yaml`
- Modify: `run_system.py`
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Delete: `agents-docker.yaml`

- [ ] **Step 1: Rewrite `agents.yaml`**

```yaml
agents:
  # ── MCP agent (config-only, no code needed) ───────────────────────────────
  - name: "Database Agent"
    type: mcp
    port: 8001
    description: "Full database access: schema inspection, SELECT, INSERT, DELETE queries"
    mcp_url: "https://mcp.neon.tech/mcp"
    auth:
      type: bearer
      env_var: NEON_API_KEY
    tools: ["get_database_tables", "describe_table_schema", "run_sql"]
    system_prompt: |
      You are DatabaseAgent, a database assistant with full access.

      Use the available MCP tools to inspect schema and execute SQL queries.
      Consider tables from all user-defined schemas.
      Ignore system/internal schemas (pg_catalog, information_schema, etc.).
      Always query the actual database. Never fabricate schema information.

      If an operation fails, report the error clearly and stop.
      Do not retry the same failing operation.
    skills:
      - id: database-ops
        name: Database Operations
        description: "Schema inspection and SQL queries (SELECT, INSERT, DELETE)"
        tags: [database, sql]

  # ── Graph agent (multi-step workflow) ─────────────────────────────────────
  - name: "Graph Reviewer"
    type: custom
    port: 8002
    description: "Multi-step reasoning: analyze, implement, review with revision loops"
    module: "agents.graph_reviewer"
    factory: "create_agent"
    skills:
      - id: multi-step-reasoning
        name: Multi-Step Reasoning
        description: "Structured graph workflow with automatic revision cycles"
        tags: [reasoning, analysis, review]

  # ── Swarm agent (autonomous team) ─────────────────────────────────────────
  - name: "Research Team"
    type: custom
    port: 8003
    description: "Collaborative research team: researcher, writer, editor with autonomous handoffs"
    module: "agents.research_team"
    factory: "create_agent"
    skills:
      - id: collaborative-research
        name: Collaborative Research
        description: "Multi-agent research, writing, and editing"
        tags: [research, writing, collaboration]
```

- [ ] **Step 2: Update `run_system.py`**

Replace:
```python
from agents.mcp_agent import load_agents_config
```
With:
```python
from core.server import load_agents_config
```

In the `_load_agents_config()` function — this is already a local wrapper, just update it:
```python
def _load_agents_config() -> list[dict]:
    """Load agent definitions from the YAML config."""
    from core.server import load_agents_config

    config_path = os.environ.get("AGENTS_CONFIG", "agents.yaml")
    return load_agents_config(config_path)
```

Update the MCP agent subprocess command in the `main()` function. Replace:
```python
            cmd = [
                python,
                "-m",
                "agents.mcp_agent",
                "--config",
                config_path,
                "--agent",
                cfg["name"],
            ]
```
With:
```python
            cmd = [
                python,
                "-m",
                "core.server",
                "--config",
                config_path,
                "--agent",
                cfg["name"],
            ]
```

Update the orchestrator subprocess command. Replace:
```python
    orch = subprocess.Popen([python, "-m", "agents.orchestrator_agent"])
```
With:
```python
    orch = subprocess.Popen([python, "-m", "core.orchestrator"])
```

Update the direct mode exec. Replace:
```python
        os.execvp(python, [python, "-m", "agents.orchestrator_agent"])
```
With:
```python
        os.execvp(python, [python, "-m", "core.orchestrator"])
```

Update the startup message. Replace:
```python
    print("All components started. Send requests to http://localhost:8000/query")
```
With:
```python
    print("All components started. Send requests to http://localhost:8000")
```

- [ ] **Step 3: Update `Dockerfile`**

```dockerfile
FROM python:3.13-slim

WORKDIR /app

# Install dependencies (cached layer).
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code.
COPY core/ core/
COPY agents/ agents/
COPY db/ db/
COPY frontend/ frontend/

EXPOSE 8000

# Default: run orchestrator (pair with agents via docker-compose).
CMD ["python", "-m", "core.orchestrator"]
```

- [ ] **Step 4: Rewrite `docker-compose.yml`**

```yaml
services:
  orchestrator:
    build: .
    command: ["python", "-m", "core.orchestrator"]
    env_file: .env
    ports:
      - "8000:8000"
    environment:
      DATABASE_MODE: "a2a"
      AGENTS_CONFIG: "/app/agents.yaml"
    volumes:
      - ./agents.yaml:/app/agents.yaml:ro
    depends_on:
      - database-agent
      - graph-reviewer
      - research-team
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

  database-agent:
    build: .
    command: ["python", "-m", "core.server", "--config", "/app/agents.yaml", "--agent", "Database Agent"]
    env_file: .env
    ports:
      - "8001:8001"
    volumes:
      - ./agents.yaml:/app/agents.yaml:ro
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/.well-known/agent-card.json"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

  graph-reviewer:
    build: .
    command: ["python", "-m", "agents.graph_reviewer"]
    env_file: .env
    ports:
      - "8002:8002"
    volumes:
      - ./agents.yaml:/app/agents.yaml:ro
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8002/.well-known/agent-card.json"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

  research-team:
    build: .
    command: ["python", "-m", "agents.research_team"]
    env_file: .env
    ports:
      - "8003:8003"
    volumes:
      - ./agents.yaml:/app/agents.yaml:ro
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8003/.well-known/agent-card.json"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

- [ ] **Step 5: Delete `agents-docker.yaml`**

```bash
git rm agents-docker.yaml
```

- [ ] **Step 6: Commit**

```bash
git add agents.yaml run_system.py Dockerfile docker-compose.yml
git commit -m "feat: update system config for core/ structure and 3-agent setup"
```

---

### Task 6: Update `db/repository.py` imports

**Files:**
- Modify: `db/repository.py`

- [ ] **Step 1: Update import**

Change:
```python
from common.schemas import ActivityEvent, Conversation, ConversationStatus, Message
```
To:
```python
from core.schemas import ActivityEvent, Conversation, ConversationStatus, Message
```

- [ ] **Step 2: Commit**

```bash
git add db/repository.py
git commit -m "refactor: update db/repository.py imports to core.*"
```

---

### Task 7: Update `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update isort known-first-party**

Change:
```toml
known-first-party = ["agents", "common", "db", "mcp_client", "tools"]
```
To:
```toml
known-first-party = ["core", "agents", "db"]
```

- [ ] **Step 2: Commit**

```bash
git add pyproject.toml
git commit -m "refactor: update pyproject.toml for core/ package structure"
```

---

### Task 8: Update all tests — import rewiring

Every test file that imports from `common.*`, `agents.model`, `agents.mcp_agent`, `agents.orchestrator_agent`, `mcp_client.*`, or `tools.*` needs updating.

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/test_store.py`
- Modify: `tests/unit/test_common.py` → rename to `tests/unit/test_core.py`
- Modify: `tests/unit/test_schemas.py`
- Modify: `tests/unit/test_agents_config.py`
- Modify: `tests/unit/test_mcp_agent.py` → rename to `tests/unit/test_mcp.py`
- Modify: `tests/unit/test_mcp_client.py` → merge into `tests/unit/test_mcp.py`
- Modify: `tests/unit/test_server_url.py`
- Modify: `tests/integration/test_a2a_server.py`
- Modify: `tests/integration/test_agent_card.py`
- Modify: `tests/e2e/test_e2e_stub.py`

- [ ] **Step 1: Update `tests/conftest.py`**

Replace:
```python
from common.store import conversation_store
```
With:
```python
from core.store import conversation_store
```

Replace the `_reset_agent` fixture:
```python
@pytest.fixture(autouse=True)
def _reset_agent():
    """Reset the lazy-loaded agent singleton between tests."""
    import agents.orchestrator_agent as orch

    orch._agent = None
    yield
    orch._agent = None
```
With:
```python
@pytest.fixture(autouse=True)
def _reset_agent():
    """Reset the lazy-loaded agent singleton between tests."""
    import core.orchestrator as orch

    orch._agent = None
    yield
    orch._agent = None
```

Replace the `_make_mock_agents` patch targets:
```python
        patch("agents.model.create_model", return_value=mock_model),
        patch("agents.mcp_agent.create_mcp_agent", return_value=mock_agent),
        patch(
            "agents.orchestrator_agent.create_safety_reviewer",
            return_value=mock_agent,
        ),
        patch(
            "agents.orchestrator_agent.review_delete_request",
            return_value=review_return,
        ),
```
With:
```python
        patch("core.model.create_model", return_value=mock_model),
        patch("core.server.create_mcp_agent", return_value=mock_agent),
        patch(
            "core.orchestrator.create_safety_reviewer",
            return_value=mock_agent,
        ),
        patch(
            "core.orchestrator.review_delete_request",
            return_value=review_return,
        ),
```

Replace client fixture imports:
```python
    from agents.orchestrator_agent import app
```
With:
```python
    from core.orchestrator import app
```

(This appears in both `client` and `client_approve` fixtures.)

- [ ] **Step 2: Update `tests/test_store.py`**

Replace:
```python
from common.schemas import ActivityEvent, Conversation, ConversationStatus, Message
from common.store import InMemoryConversationStore
```
With:
```python
from core.schemas import ActivityEvent, Conversation, ConversationStatus, Message
from core.store import InMemoryConversationStore
```

- [ ] **Step 3: Update `tests/unit/test_schemas.py`**

Replace:
```python
from common.schemas import (
    ActivityEvent,
    Conversation,
    ConversationStatus,
    ConversationSummary,
    Message,
    MessageRequest,
)
```
With:
```python
from core.schemas import (
    ActivityEvent,
    Conversation,
    ConversationStatus,
    ConversationSummary,
    Message,
    MessageRequest,
)
```

- [ ] **Step 4: Rename and update `tests/unit/test_common.py` → `tests/unit/test_core.py`**

```bash
git mv tests/unit/test_common.py tests/unit/test_core.py
```

In `tests/unit/test_core.py`, replace all `from common.task_store` with `from core.task_store`, all `from common.logging_setup` with `from core.logging`, and all `from common.auth` with `from core.auth`.

Specifically, replace every occurrence of:
- `from common.task_store import InMemoryA2ATaskStore` → `from core.task_store import InMemoryA2ATaskStore`
- `from common.logging_setup import StructuredJsonFormatter` → `from core.logging import StructuredJsonFormatter`
- `from common.auth import AgentAuthMiddleware` → `from core.auth import AgentAuthMiddleware`

- [ ] **Step 5: Create `tests/unit/test_mcp.py` by merging test_mcp_agent.py and test_mcp_client.py**

Create `tests/unit/test_mcp.py` with all tests from both files, updating import paths:

```python
"""Tests for the MCP agent factory and MCP client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ── MCP Agent Factory (core.server) ─────────────────────────────────────────


def test_create_mcp_agent_returns_agent():
    """create_mcp_agent should return a Strands Agent with correct config."""
    mock_client = MagicMock()
    mock_model = MagicMock()

    config = {
        "name": "Test Agent",
        "mcp_url": "https://example.com/mcp",
        "description": "A test agent",
        "system_prompt": "You are a test agent.",
    }

    with (
        patch("core.server.create_mcp_client", return_value=mock_client),
        patch("core.server.create_model", return_value=mock_model),
        patch("core.server.Agent") as mock_agent_cls,
    ):
        from core.server import create_mcp_agent

        create_mcp_agent(config)

        mock_agent_cls.assert_called_once_with(
            model=mock_model,
            name="Test Agent",
            description="A test agent",
            system_prompt="You are a test agent.",
            tools=[mock_client],
            callback_handler=None,
        )


def test_create_mcp_agent_passes_auth():
    """create_mcp_agent should forward auth config to create_mcp_client."""
    mock_client = MagicMock()

    config = {
        "name": "Auth Agent",
        "mcp_url": "https://example.com/mcp",
        "auth": {"type": "bearer", "env_var": "MY_TOKEN"},
    }

    with (
        patch("core.server.create_mcp_client", return_value=mock_client) as mock_get,
        patch("core.server.create_model", return_value=MagicMock()),
        patch("core.server.Agent"),
    ):
        from core.server import create_mcp_agent

        create_mcp_agent(config)

        mock_get.assert_called_once_with(
            mcp_url="https://example.com/mcp",
            auth={"type": "bearer", "env_var": "MY_TOKEN"},
        )


def test_create_mcp_agent_default_system_prompt():
    """create_mcp_agent should use default system prompt when none provided."""
    config = {
        "name": "Minimal Agent",
        "mcp_url": "https://example.com/mcp",
    }

    with (
        patch("core.server.create_mcp_client", return_value=MagicMock()),
        patch("core.server.create_model", return_value=MagicMock()),
        patch("core.server.Agent") as mock_agent_cls,
    ):
        from core.server import create_mcp_agent

        create_mcp_agent(config)

        call_kwargs = mock_agent_cls.call_args[1]
        assert call_kwargs["system_prompt"] == "Use the available tools."


def test_load_agents_config_reads_yaml(tmp_path):
    """load_agents_config should parse agents.yaml and return the agents list."""
    import yaml

    config = {
        "agents": [
            {
                "name": "A1",
                "type": "mcp",
                "port": 9001,
                "mcp_url": "https://example.com/mcp",
                "tools": [],
                "skills": [],
            },
        ]
    }
    config_path = tmp_path / "agents.yaml"
    config_path.write_text(yaml.dump(config))

    from core.server import load_agents_config

    agents = load_agents_config(str(config_path))
    assert len(agents) == 1
    assert agents[0]["name"] == "A1"


# ── MCP Client (core.mcp) ───────────────────────────────────────────────────


def test_create_mcp_client_no_auth():
    """create_mcp_client without auth should create client with no auth headers."""
    with patch("core.mcp.streamable_http_client"):
        from core.mcp import create_mcp_client

        client = create_mcp_client("https://example.com/mcp")
        assert client is not None


def test_create_mcp_client_bearer_auth(monkeypatch):
    """create_mcp_client with bearer auth should read token from env."""
    monkeypatch.setenv("MY_TOKEN", "secret-123")
    with patch("core.mcp.streamable_http_client"):
        from core.mcp import create_mcp_client

        client = create_mcp_client(
            "https://example.com/mcp",
            auth={"type": "bearer", "env_var": "MY_TOKEN"},
        )
        assert client is not None


def test_create_mcp_client_bearer_auth_missing_env():
    """create_mcp_client with bearer auth should raise when env var is missing."""
    import os

    os.environ.pop("MISSING_TOKEN", None)

    with patch("core.mcp.streamable_http_client"):
        import pytest

        from core.mcp import create_mcp_client

        with pytest.raises(KeyError):
            create_mcp_client(
                "https://example.com/mcp",
                auth={"type": "bearer", "env_var": "MISSING_TOKEN"},
            )


def test_create_mcp_client_returns_reconnecting_subclass():
    """create_mcp_client should return a ReconnectingMCPClient."""
    with patch("core.mcp.streamable_http_client"):
        from core.mcp import ReconnectingMCPClient, create_mcp_client

        client = create_mcp_client("https://example.com/mcp")
        assert isinstance(client, ReconnectingMCPClient)


def test_reconnecting_client_calls_stop_and_start_on_dead_session():
    """ReconnectingMCPClient should stop+start when session is dead."""
    with patch("core.mcp.streamable_http_client"):
        from core.mcp import create_mcp_client

        client = create_mcp_client("https://example.com/mcp")

        # Simulate a dead session
        client._background_thread = MagicMock()
        client._background_thread.is_alive.return_value = False
        client._close_future = MagicMock()
        client._close_future.done.return_value = True

        # Patch stop and start to prevent actual connection attempts
        client.stop = MagicMock()
        client.start = MagicMock()

        client._reconnect()

        client.stop.assert_called_once_with(None, None, None)
        client.start.assert_called_once()
```

Then delete the old files:
```bash
git rm tests/unit/test_mcp_agent.py tests/unit/test_mcp_client.py
```

- [ ] **Step 6: Update `tests/unit/test_server_url.py`**

Replace all `common.server` patch targets with `core.server`:
- `patch("common.server.configure_logging")` → `patch("core.server.configure_logging")`
- `patch("common.server.configure_tracing")` → `patch("core.server.configure_tracing")`
- `patch("common.server.A2AServer")` → `patch("core.server.A2AServer")`
- `patch("common.server.uvicorn")` → `patch("core.server.uvicorn")`
- `from common.server import serve_agent` → `from core.server import serve_agent`

- [ ] **Step 7: Update `tests/integration/test_a2a_server.py`**

Replace all import/patch targets:
- `patch("agents.model.create_model", ...)` → `patch("core.model.create_model", ...)`
- `patch("mcp_client.client.create_mcp_client", ...)` → `patch("core.mcp.create_mcp_client", ...)`
- `patch("common.logging_setup.configure_logging")` → `patch("core.logging.configure_logging")`
- `patch("common.tracing.configure_tracing")` → `patch("core.tracing.configure_tracing")`
- `from agents.mcp_agent import create_mcp_agent` → `from core.server import create_mcp_agent`
- `from common.task_store import InMemoryA2ATaskStore` → `from core.task_store import InMemoryA2ATaskStore`
- `from common.auth import AgentAuthMiddleware` → `from core.auth import AgentAuthMiddleware`

- [ ] **Step 8: Update `tests/integration/test_agent_card.py`**

Same replacements as test_a2a_server.py:
- `patch("agents.model.create_model", ...)` → `patch("core.model.create_model", ...)`
- `patch("mcp_client.client.create_mcp_client", ...)` → `patch("core.mcp.create_mcp_client", ...)`
- `patch("common.logging_setup.configure_logging")` → `patch("core.logging.configure_logging")`
- `patch("common.tracing.configure_tracing")` → `patch("core.tracing.configure_tracing")`
- `from agents.mcp_agent import create_mcp_agent` → `from core.server import create_mcp_agent`
- `from common.task_store import InMemoryA2ATaskStore` → `from core.task_store import InMemoryA2ATaskStore`

- [ ] **Step 9: Update `tests/e2e/test_e2e_stub.py`**

Update agent card test expectations. Replace:
```python
    assert card["name"] == "Database Reader"
```
With:
```python
    assert card["name"] == "Database Agent"
```

Replace:
```python
    assert card["name"] == "Graph Agent"
```
With:
```python
    assert card["name"] == "Graph Reviewer"
```

Update the env var name:
```python
    db_agent_url = os.environ.get("DB_READER_URL", "http://localhost:8001/")
```
To:
```python
    db_agent_url = os.environ.get("DB_AGENT_URL", "http://localhost:8001/")
```

- [ ] **Step 10: Run the full test suite**

```bash
pytest -x -v
```

Expected: All tests pass (82 passed, 4 skipped).

- [ ] **Step 11: Commit**

```bash
git add tests/
git commit -m "refactor: update all test imports from common/agents to core"
```

---

### Task 9: Delete old packages

Remove the old `common/`, `mcp_client/`, `tools/`, and moved files from `agents/`.

**Files:**
- Delete: `common/` (entire package)
- Delete: `mcp_client/` (entire package)
- Delete: `tools/` (entire package)
- Delete: `agents/orchestrator_agent.py`
- Delete: `agents/model.py`
- Delete: `agents/mcp_agent.py`
- Delete: `agents/graph_agent.py`

- [ ] **Step 1: Remove old files**

```bash
git rm -r common/
git rm -r mcp_client/
git rm -r tools/
git rm agents/orchestrator_agent.py agents/model.py agents/mcp_agent.py agents/graph_agent.py
```

- [ ] **Step 2: Run tests to confirm nothing is broken**

```bash
pytest -x -v
```

Expected: All tests pass.

- [ ] **Step 3: Run linter**

```bash
ruff check .
ruff format .
```

Expected: All checks passed.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: remove old common/, mcp_client/, tools/ packages"
```

---

### Task 10: Add examples

Add standalone pattern examples in `examples/`.

**Files:**
- Modify: `examples/graph_agent.py` (already exists — update imports)
- Modify: `examples/swarm_agent.py` (already exists — no changes needed)
- Create: `examples/mcp_agent.py`
- Create: `examples/pipeline_agent.py`

- [ ] **Step 1: Update `examples/graph_agent.py` — no import changes needed**

This file uses `from strands import Agent` and `from strands.multiagent import GraphBuilder` directly. No `common.*` or `agents.*` imports. No changes needed.

- [ ] **Step 2: `examples/swarm_agent.py` — no changes needed**

This file uses `from strands import Agent` and `from strands.multiagent import Swarm` directly. No changes needed.

- [ ] **Step 3: Write `examples/mcp_agent.py`**

```python
"""Minimal MCP agent — the simplest way to create an A2A agent from an MCP server.

Usage:
    NEON_API_KEY=... python examples/mcp_agent.py
"""

from dotenv import load_dotenv

load_dotenv()

from core.mcp import create_mcp_client
from core.model import create_model
from core.server import serve_agent
from strands import Agent

client = create_mcp_client(
    mcp_url="https://mcp.neon.tech/mcp",
    auth={"type": "bearer", "env_var": "NEON_API_KEY"},
)

agent = Agent(
    model=create_model(),
    name="My MCP Agent",
    description="Queries a database via MCP",
    system_prompt="You are a database assistant. Use the available tools.",
    tools=[client],
    callback_handler=None,
)

serve_agent(agent, name="my-mcp-agent", port=8010)
```

- [ ] **Step 4: Write `examples/pipeline_agent.py`**

```python
"""Pipeline agent — a Graph that orchestrates remote A2A agents as nodes.

Demonstrates composing other people's A2A agents into your own workflow.
Requires the database agent and graph reviewer to be running:

    python run_system.py   # starts all agents
    python examples/pipeline_agent.py  # in another terminal

Usage:
    python examples/pipeline_agent.py
"""

from dotenv import load_dotenv

load_dotenv()

from strands import Agent
from strands.agent.a2a_agent import A2AAgent
from strands.multiagent import GraphBuilder

from core.model import create_model
from core.server import serve_agent

# Remote agents (other A2A servers — could be anyone's)
db_agent = A2AAgent(endpoint="http://localhost:8001", name="database")
reviewer = A2AAgent(endpoint="http://localhost:8002", name="graph_reviewer")

# Local agent for summarization
summarizer = Agent(
    model=create_model(),
    name="summarizer",
    system_prompt="Summarize the results from previous agents clearly and concisely.",
    callback_handler=None,
)

# Wire them into a graph
builder = GraphBuilder()
builder.add_node(db_agent, "fetch_data")
builder.add_node(reviewer, "review")
builder.add_node(summarizer, "summarize")
builder.add_edge("fetch_data", "review")
builder.add_edge("review", "summarize")
builder.set_entry_point("fetch_data")

graph = builder.build()
graph.name = "Pipeline Agent"  # type: ignore[attr-defined]
graph.description = "Fetches data, reviews, and summarizes"  # type: ignore[attr-defined]

serve_agent(graph, name="pipeline-agent", port=8010)
```

- [ ] **Step 5: Commit**

```bash
git add examples/
git commit -m "feat: add mcp_agent and pipeline_agent examples"
```

---

### Task 11: Update documentation

Rewrite CLAUDE.md, README.md, and EXTENDING.md to reflect the new structure.

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `EXTENDING.md`

- [ ] **Step 1: Rewrite `CLAUDE.md`**

Update all sections:
- Project Overview: mention `core/` and `agents/` split
- Commands: update `python -m` commands to `core.orchestrator`, `core.server`
- Architecture: update Agent Topology, Orchestrator section to say `core/orchestrator.py`
- MCP Agents section: reference `core/server.py` for `create_mcp_agent()`
- Graph Agent: reference `agents/graph_reviewer.py`
- MCP Client: reference `core/mcp.py`
- Safety Review: reference `core/safety.py`
- Shared Utilities: rename to `Core Framework (core/)`, update all file paths
- Model Configuration: reference `core/model.py`
- Testing Patterns: update patch paths (`core.server.create_mcp_agent`, `core.orchestrator.*`)
- Code Style: update isort known-first-party to `core`, `agents`, `db`

Every reference to `common.*`, `agents/orchestrator_agent.py`, `agents/model.py`, `agents/mcp_agent.py`, `mcp_client/`, `tools/` must be updated to the new `core/` paths.

- [ ] **Step 2: Rewrite `README.md`**

Update:
- Architecture diagram: show `core/` as framework
- Project structure tree: reflect new directory layout
- "Adding a New Agent" section: show all 4 patterns (MCP via YAML, custom Agent, Graph, Swarm)
- Commands: update `python -m` paths
- Testing section: update test file names

- [ ] **Step 3: Rewrite `EXTENDING.md`**

Update:
- Architecture diagram: show `core/` as framework, 3 demo agents
- All code examples: use `core.*` imports
- "Adding a New Agent" sections: MCP (YAML-only), Graph, Swarm, Pipeline patterns
- "Persistent Storage": reference `core.store`, `ConversationStore` protocol
- Remove all references to `common/`, `mcp_client/`, `tools/`, `agents/mcp_agent.py`

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md EXTENDING.md
git commit -m "docs: rewrite all documentation for core/ restructure"
```

---

### Task 12: Final verification and cleanup

**Files:** None created — verification only.

- [ ] **Step 1: Run full test suite**

```bash
pytest -v
```

Expected: All tests pass.

- [ ] **Step 2: Run linter and formatter**

```bash
ruff check .
ruff format --check .
```

Expected: All checks passed.

- [ ] **Step 3: Run type checker**

```bash
mypy core/ agents/ db/
```

Expected: No errors (or only pre-existing ones).

- [ ] **Step 4: Verify no old imports remain**

```bash
grep -r "from common\." --include="*.py" . | grep -v ".venv" | grep -v __pycache__
grep -r "from mcp_client\." --include="*.py" . | grep -v ".venv" | grep -v __pycache__
grep -r "from tools\." --include="*.py" . | grep -v ".venv" | grep -v __pycache__
grep -r "from agents\.model" --include="*.py" . | grep -v ".venv" | grep -v __pycache__
grep -r "from agents\.orchestrator_agent" --include="*.py" . | grep -v ".venv" | grep -v __pycache__
grep -r "from agents\.mcp_agent" --include="*.py" . | grep -v ".venv" | grep -v __pycache__
```

Expected: No output from any of these commands.

- [ ] **Step 5: Verify old directories are gone**

```bash
ls common/ 2>&1 || echo "common/ removed ✓"
ls mcp_client/ 2>&1 || echo "mcp_client/ removed ✓"
ls tools/ 2>&1 || echo "tools/ removed ✓"
ls agents/orchestrator_agent.py 2>&1 || echo "orchestrator_agent.py removed ✓"
ls agents/model.py 2>&1 || echo "model.py removed ✓"
ls agents/mcp_agent.py 2>&1 || echo "mcp_agent.py removed ✓"
```

Expected: All removed.

- [ ] **Step 6: Run the system in direct mode (smoke test)**

```bash
timeout 5 python -c "from core.orchestrator import app; print('App loaded OK')" || true
```

Expected: `App loaded OK`

- [ ] **Step 7: Final commit if any formatting changes**

```bash
ruff format .
git add -A
git diff --cached --quiet || git commit -m "style: apply ruff formatting after restructure"
```
