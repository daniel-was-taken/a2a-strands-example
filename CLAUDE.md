# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A2A (Agent-to-Agent) framework built with Strands Agents SDK. Agents are declared in `agents.yaml` and spun up dynamically -- no Python code changes needed to add a new MCP-backed agent. The framework provides the plumbing (serving, auth, logging, tracing, MCP connectivity) so users can focus on agent definitions.

The codebase has a clear boundary: `core/` is the framework (don't modify), `agents/` is user agents (fork and customize).

**LLM:** Google Gemini (configurable via `GEMINI_MODEL_ID`, default `gemini-2.5-flash`)
**MCP:** Any MCP server (configured per-agent in `agents.yaml`)
**Framework:** FastAPI + Strands A2A SDK

## Commands

```bash
# Install dependencies
pip install -e ".[dev]"           # dev (includes test/lint tools)
pip install -e ".[otel]"          # with OpenTelemetry tracing

# Run the system
python run_system.py              # starts all agents from agents.yaml

# Run individual agents
python -m core.server --config agents.yaml --agent "Database Agent"     # MCP agent
python -m agents.graph_reviewer                                          # Port 8002 (custom agent)
python -m agents.research_team                                           # Port 8003 (custom agent)

# Docker
docker compose up --build

# Tests
pytest                            # All tests
pytest tests/unit/test_core.py    # Single file
pytest tests/unit/test_core.py::test_function  # Single test
pytest -x                         # Stop on first failure

# Lint & format
ruff check .                      # Lint
ruff check --fix .                # Auto-fix
ruff format .                     # Format

# Type checking
mypy core/ agents/
```

## Architecture

### Agent Topology

```
[Agents declared in agents.yaml]
├─ Database Agent   (MCP, port 8001)
├─ Graph Reviewer   (custom, port 8002)
├─ Research Team    (custom, port 8003)
├─ DeepWiki Agent   (MCP, port 8004)
└─ Kaggle Agent     (MCP, port 8005)
```

Each agent runs as a separate process/container, exposed as an A2A server over HTTP. `run_system.py` reads `agents.yaml` and starts all declared agents as subprocesses, waits for health checks, then monitors for crashes.

### MCP Agents (config-driven) (`core/server.py`)

Generic factory that creates Strands Agents from `agents.yaml`. Each YAML entry with `type: mcp` declares a name, description, system prompt, MCP server URL, and auth block. The factory connects to the MCP server, builds a Strands Agent with the resolved tools, and serves it via `serve_agent()`. Key functions: `create_mcp_agent()`, `serve_mcp_agent()`, `load_agents_config()`, `serve_agent()`.

**`agents.yaml` format** -- two agent types:
- `type: mcp` -- config-driven: MCP server URL, auth (env-var references), system prompt for tool filtering
- `type: custom` -- Python factory function (e.g. Graph Reviewer), referenced by module path and factory name

**CLI:** `python -m core.server --config agents.yaml --agent "<name>"` starts one MCP agent by name.

### Graph Reviewer (`agents/graph_reviewer.py`)

A2A server (via `serve_agent()`) using Strands GraphBuilder for multi-step reasoning: analyze -> implement -> review, with conditional loops back to implement if review says "needs revision" (max 5 iterations). Uses `callback_handler=None` and `load_tools_from_directory=False` on all sub-agents. Includes a `NoToolsGeminiModel` subclass to work around a Gemini API bug with empty tool declarations.

### Research Team (`agents/research_team.py`)

A2A server demonstrating the Swarm pattern: autonomous agent handoffs where agents (researcher, writer, editor) transfer control to each other based on context. Configured with `max_handoffs=10`, `max_iterations=15`, `execution_timeout=300.0`.

### MCP Client (`core/mcp.py`)

Generic MCP client factory. `create_mcp_client()` returns a `ReconnectingMCPClient` that transparently reconnects when the underlying session dies (e.g. idle-timeout from the MCP server). The reconnect cycle is stop -> start, which resets all internal state including `_init_future`. Also handles malformed MCP server responses (e.g. servers returning plain strings instead of `list[Content]`) by wrapping them as text results.

### Core Framework (`core/`)

- `config.py` -- Pydantic Settings: single source of truth for all env vars. Fields: `allowed_origins`, `agents_config`, `google_api_key`, `google_cloud_project`, `google_cloud_location`, `gemini_model_id`, `agent_api_key`
- `server.py` -- `serve_agent()` helper: starts any Strands agent (Agent, Graph, or Swarm) as an A2A server with auth, CORS, structured logging, and tracing. Also contains `create_mcp_agent()`, `serve_mcp_agent()`, `load_agents_config()`. All agents use this instead of duplicating server boilerplate.
- `mcp.py` -- `ReconnectingMCPClient` + `create_mcp_client()` factory (see above)
- `model.py` -- Shared Gemini model factory (`create_model()`)
- `auth.py` -- `AgentAuthMiddleware`: X-Agent-API-Key validation on A2A agents (no-op when key is empty; always exempt: `/.well-known/agent-card.json`, `/health`, `/ready`)
- `logging.py` -- Structured JSON logging with `agent_name`, `task_id`, `session_id`, `duration_ms` fields
- `task_store.py` -- Thread-safe in-memory A2A TaskStore (swap for Redis/DynamoDB in multi-replica deployments)
- `tracing.py` -- OpenTelemetry OTLP setup (no-op when endpoint not configured)

### Model Configuration (`core/model.py`)

All agents share `create_model()` which returns a `GeminiModel`. Uses `GOOGLE_API_KEY` for local dev (Google AI Studio) or Vertex AI via ADC when `GOOGLE_CLOUD_PROJECT` is set.

### Examples (`examples/`)

Standalone scripts demonstrating framework patterns:
- `mcp_agent.py` -- Minimal MCP agent: create client, build agent, serve via A2A
- `a2a_graph.py` -- GraphBuilder with conditional routing (no A2A, runs locally)
- `a2a_swarm.py` -- Swarm with autonomous handoffs (no A2A, runs locally)
- `pipeline_agent.py` -- Graph that orchestrates remote A2A agents (A2AAgent) as nodes, composing other services into a pipeline

## Testing Patterns

- All tests mock LLM calls completely -- no real API keys needed
- `conftest.py` sets env vars at import time (before `Settings()` singleton is created) and also via `monkeypatch` per-test
- Agent mock patches `core.server.create_mcp_agent`; uses `MagicMock` (not `AsyncMock`) because `Agent.__call__` is synchronous
- Test YAML config is written to a temp file and pointed to via `AGENTS_CONFIG`
- Async tests run automatically via `pytest-asyncio` with `asyncio_mode = "auto"`
- Tests are organized into `tests/unit/` and `tests/integration/`

## Configuration

All configuration flows through `core/config.py` (Pydantic Settings) and `.env`. Copy `.env.example` to `.env` for local development. Required vars: `AGENTS_CONFIG` (path to `agents.yaml`, defaults to `agents.yaml`), and either `GOOGLE_API_KEY` or `GOOGLE_CLOUD_PROJECT`. MCP server credentials (API keys, project IDs, etc.) are referenced by `agents.yaml` auth blocks and should be set as env vars.

## Code Style

- Python 3.11+, line length 100
- Ruff for linting/formatting (config in `pyproject.toml`)
- Mypy strict mode (excludes tests)
- Known first-party packages for import sorting: `core`, `agents`
- Ruff rule sets: `E`, `F`, `W`, `I`, `UP`, `B`, `C4`, `SIM`
- Ruff ignores: `B008` (FastAPI `Depends()` pattern), `UP007` (keep `Optional[]` over `X | Y`)
- `TCH` rules intentionally excluded -- causes false positives with Protocol definitions and Pydantic models
