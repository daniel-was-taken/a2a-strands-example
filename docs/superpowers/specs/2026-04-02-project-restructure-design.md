# Project Restructure: Framework + Reference Implementation

**Date:** 2026-04-02
**Status:** Approved

## Goal

Restructure the project so forkers see a clear boundary between framework code (`core/`) and user-customizable agents (`agents/`). Simplify by merging redundant packages, consolidating 3 database agents into 1, adding swarm demo agent, and providing standalone examples for all 4 agent patterns (MCP, Graph, Swarm, Pipeline).

## Non-Goals

- Changing the orchestrator's REST API or conversation model
- Changing the frontend
- Adding new framework features (persistence backends, auth providers, etc.)
- Replacing A2A with Swarm as the inter-agent protocol

## Directory Structure (After)

```
a2a-strands-example/
├── core/                        # Framework — don't modify
│   ├── __init__.py
│   ├── orchestrator.py          # FastAPI app, conversations, safety, routing
│   ├── server.py                # serve_agent() + create_mcp_agent() + serve_mcp_agent()
│   ├── model.py                 # LLM factory (Gemini, swappable)
│   ├── mcp.py                   # Reconnecting MCP client factory
│   ├── safety.py                # LLM-based safety reviewer
│   ├── config.py                # Pydantic Settings (env vars)
│   ├── schemas.py               # Conversation, Message, etc.
│   ├── store.py                 # ConversationStore protocol + InMemory
│   ├── auth.py                  # X-Agent-API-Key middleware
│   ├── log_stream.py            # SSE broadcaster
│   ├── logging.py               # Structured JSON logging
│   ├── task_store.py            # A2A TaskStore
│   └── tracing.py               # OpenTelemetry (conditional)
├── agents/                      # User agents — fork and customize
│   ├── __init__.py
│   ├── graph_reviewer.py        # Demo: Graph workflow (analyze→implement→review)
│   └── research_team.py         # Demo: Swarm agent (researcher→writer→editor)
├── examples/                    # Standalone pattern snippets (educational)
│   ├── mcp_agent.py             # Minimal MCP agent
│   ├── graph_agent.py           # Minimal graph (exists)
│   ├── swarm_agent.py           # Minimal swarm (exists)
│   └── pipeline_agent.py        # Graph with remote A2AAgent nodes
├── db/                          # Optional PostgreSQL backend
│   └── repository.py
├── frontend/                    # ChatGPT-style UI (unchanged)
│   ├── index.html
│   ├── style.css
│   └── app.js
├── agents.yaml                  # Agent declarations (3 demo agents)
├── run_system.py                # Multi-process launcher
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── tests/
│   ├── conftest.py
│   ├── test_orchestrator.py
│   ├── test_store.py
│   ├── test_smoke.py
│   ├── unit/
│   │   ├── test_core.py         # Was test_common.py
│   │   ├── test_schemas.py
│   │   ├── test_agents_config.py
│   │   ├── test_mcp.py          # Merges test_mcp_agent.py + test_mcp_client.py
│   │   └── test_server_url.py
│   ├── integration/
│   │   ├── test_a2a_server.py
│   │   └── test_agent_card.py
│   └── e2e/
│       └── test_e2e_stub.py
```

## File Moves and Merges

### Pure renames (no logic changes, only import paths)

| From | To |
|------|----|
| `common/__init__.py` | `core/__init__.py` |
| `common/config.py` | `core/config.py` |
| `common/schemas.py` | `core/schemas.py` |
| `common/store.py` | `core/store.py` |
| `common/auth.py` | `core/auth.py` |
| `common/log_stream.py` | `core/log_stream.py` |
| `common/task_store.py` | `core/task_store.py` |
| `common/tracing.py` | `core/tracing.py` |
| `common/server.py` | `core/server.py` |
| `common/logging_setup.py` | `core/logging.py` |
| `agents/model.py` | `core/model.py` |
| `mcp_client/client.py` | `core/mcp.py` |
| `tools/safety_reviewer.py` | `core/safety.py` |

### Merges

| From | Into | What moves |
|------|------|------------|
| `agents/mcp_agent.py` | `core/server.py` | `create_mcp_agent()`, `serve_mcp_agent()`, `load_agents_config()` |

`core/server.py` gains a `__main__` block so MCP agents can be started via `python -m core.server --config agents.yaml --agent "Database Agent"`. This replaces `python -m agents.mcp_agent`. `run_system.py` updates its subprocess command accordingly.

### Refactors

| File | Changes |
|------|---------|
| `agents/orchestrator_agent.py` → `core/orchestrator.py` | All imports: `common.*` → `core.*`, `agents.model` → `core.model`, `tools.safety_reviewer` → `core.safety`, `agents.mcp_agent` → `core.config`/`core.server` |
| `agents/graph_agent.py` → `agents/graph_reviewer.py` | Imports: `agents.model` → `core.model`, `common.server` → `core.server`. Factory renamed to `create_agent()`. |
| `db/repository.py` | Imports: `common.*` → `core.*` |
| `run_system.py` | Imports: `agents.mcp_agent.load_agents_config` → `core.server.load_agents_config`. MCP agent subprocess command changes from `python -m agents.mcp_agent` to `python -m core.server`. |

### Deleted

| Path | Reason |
|------|--------|
| `common/` package | Replaced by `core/` |
| `mcp_client/` package | Merged into `core/mcp.py` |
| `tools/` package | Merged into `core/safety.py` |
| `agents/orchestrator_agent.py` | Moved to `core/orchestrator.py` |
| `agents/model.py` | Moved to `core/model.py` |
| `agents/mcp_agent.py` | Split into `core/server.py` and `core/config.py` |
| `agents-docker.yaml` | Docker host overrides move to docker-compose env vars |

## New Files

### `agents/research_team.py` — Swarm demo agent

Factory function `create_agent()` returns a `Swarm` with 3 agents:
- **researcher**: gathers information, hands off to writer
- **writer**: writes clear content from research, hands off to editor
- **editor**: polishes, hands back to writer if major issues

`serve()` function wraps it via `core.server.serve_agent()` on port 8003.

~40 lines.

### `examples/pipeline_agent.py` — Graph with remote A2AAgent nodes

Standalone educational example showing:
- `A2AAgent(endpoint="http://localhost:8001")` as a graph node
- Local `Agent` as another node
- `GraphBuilder` wiring them together

Demonstrates that any A2A server (anyone's) can be a node in your graph.

~35 lines. Not registered in `agents.yaml`.

### `examples/mcp_agent.py` — Minimal MCP agent

Standalone example showing the minimum code to create and serve an MCP-backed agent. Uses `core.mcp.create_mcp_client()` and `core.server.serve_agent()`.

~25 lines.

## agents.yaml (After)

3 agents instead of 5:

1. **Database Agent** (`type: mcp`, port 8001) — merges reader/writer/deleter into one agent with full SQL access
2. **Graph Reviewer** (`type: custom`, port 8002) — graph workflow demo
3. **Research Team** (`type: custom`, port 8003) — swarm team demo

All custom agents use `factory: "create_agent"` as a consistent convention.

## Test Changes

No test logic changes. All changes are import path updates:

- `from common.*` → `from core.*`
- `from agents.model` → `from core.model`
- `from agents.orchestrator_agent` → `from core.orchestrator`
- `from agents.mcp_agent` → `from core.server` / `from core.config`
- `conftest.py` patches update to new module paths
- `test_common.py` → `test_core.py` (rename)
- `test_mcp_client.py` merged into `test_mcp.py`

## Docker Changes

`docker-compose.yml` simplifies from 5 services to 4:
- `orchestrator` (port 8000)
- `database-agent` (port 8001) — was 3 separate services
- `graph-reviewer` (port 8002)
- `research-team` (port 8003)

`agents-docker.yaml` deleted. Container hostnames set via docker-compose service names and environment variables.

## pyproject.toml Changes

```toml
[tool.ruff.lint.isort]
known-first-party = ["core", "agents", "db"]
```

Removes `mcp_client`, `tools`, `common`.

## Documentation

All three docs rewritten:
- **README.md**: updated structure tree, agent patterns, examples
- **EXTENDING.md**: rewritten around 4 patterns (MCP, Graph, Swarm, Pipeline) with fork-and-customize narrative
- **CLAUDE.md**: updated all file paths, package names, architecture section

## Composition Rules (Reference)

| Container | Agent | A2AAgent (remote) | Graph | Swarm |
|-----------|-------|--------------------|-------|-------|
| **Graph node** | Yes | Yes | Yes | Yes |
| **Swarm node** | Yes | No | No | No |
| **A2AServer** | Yes | N/A | Yes | Yes |

Graph is the universal compositor. Swarm is local-only. A2A is the network boundary.
