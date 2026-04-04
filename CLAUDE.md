# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A2A (Agent-to-Agent) multi-agent system built with Strands Agents SDK. Agents are declared in `agents.yaml` and spun up dynamically — no Python code changes needed to add a new MCP-backed agent. The orchestrator routes user queries to specialist agents via A2A, with safety review and human-in-the-loop approval for destructive operations.

The codebase has a clear boundary: `core/` is the framework (don't modify), `agents/` is user agents (fork and customize).

**LLM:** Google Gemini (configurable via `GEMINI_MODEL_ID`, default `gemini-3.5-flash`)
**MCP:** Any MCP server (configured per-agent in `agents.yaml`)
**Framework:** FastAPI (orchestrator), Strands A2A SDK (specialist agents)

## Commands

```bash
# Install dependencies
pip install -e ".[dev]"           # dev (includes test/lint tools)
pip install -e ".[otel]"          # with OpenTelemetry tracing

# Run the system
python run_system.py              # A2A mode: orchestrator + agents from agents.yaml
DATABASE_MODE=direct python run_system.py  # Direct mode: single process, no A2A

# Run individual agents
python -m core.orchestrator                                              # Port 8000
python -m core.server --config agents.yaml --agent "Database Agent"     # MCP agent
python -m agents.graph_reviewer                                          # Port 8002 (custom agent)

# Docker
docker compose up --build

# Tests
pytest                            # All tests
pytest tests/test_smoke.py        # Single file
pytest tests/test_orchestrator.py::test_send_message  # Single test
pytest -x                         # Stop on first failure

# Lint & format
ruff check .                      # Lint
ruff check --fix .                # Auto-fix
ruff format .                     # Format

# Type checking
mypy core/ agents/ db/
```

## Architecture

### Agent Topology

```
User → Orchestrator (8000) → A2A → [Agents declared in agents.yaml]
                                    ├─ Database Agent  (MCP, port 8001)
                                    ├─ Graph Reviewer  (custom, port 8002)
                                    └─ Research Team   (custom, port 8003)
```

### Two Operating Modes

- **A2A mode** (default): Orchestrator communicates with specialist agents via A2A protocol over HTTP. Each agent runs as a separate process/container.
- **Direct mode** (`DATABASE_MODE=direct`): Single process. The first MCP agent from `agents.yaml` is loaded in-process, no A2A networking. Custom agents (e.g. Graph Reviewer) unavailable.

### Orchestrator (`core/orchestrator.py`)

FastAPI app with a conversation-first data model. Receives user messages via REST, runs safety review on destructive operations (DELETE/DROP/TRUNCATE), and routes to specialist agents. Each conversation is a persistent chat thread with statuses: `active` or `awaiting_approval`. The agent singleton is lazy-loaded and thread-safe; its `messages` array is reset before each turn to prevent cross-conversation leakage, with context rebuilt from the conversation's stored messages (last 20). Agent invocations use `asyncio.to_thread` to avoid blocking the event loop.

### MCP Agents (config-driven) (`core/server.py`)

Generic factory that creates Strands Agents from `agents.yaml`. Each YAML entry with `type: mcp` declares a name, description, system prompt, MCP server URL, and auth block. The factory connects to the MCP server, builds a Strands Agent with the resolved tools, and serves it via `serve_agent()`. Key functions: `create_mcp_agent()`, `serve_mcp_agent()`, `load_agents_config()`, `serve_agent()`.

**`agents.yaml` format** — two agent types:
- `type: mcp` — config-driven: MCP server URL, auth (env-var references), system prompt for tool filtering
- `type: custom` — Python factory function (e.g. Graph Reviewer), referenced by module path

**CLI:** `python -m core.server --config agents.yaml --agent "<name>"` starts one agent by name.

### Graph Reviewer (`agents/graph_reviewer.py`)

A2A server (via `serve_agent()`) using Strands GraphBuilder for multi-step reasoning: analyze → implement → review, with conditional loops back to implement if review says "needs revision" (max 5 iterations). Uses `callback_handler=None` on all sub-agents.

### Research Team (`agents/research_team.py`)

A2A server demonstrating the Swarm pattern: autonomous agent handoffs where agents transfer control to each other based on context. Useful for parallel research tasks or multi-perspective analysis.

### MCP Client (`core/mcp.py`)

Generic MCP client factory with a connection registry keyed by URL. Multiple agents sharing the same MCP server URL reuse one connection. Same reconnect pattern (3 attempts, exponential backoff) but parameterised by URL and auth from `agents.yaml`.

### Safety Review (`core/safety.py`)

LLM-based reviewer that evaluates destructive queries. Outputs `APPROVE: reason` or `REJECT: reason`. Triggered when query matches destructive keywords.

### Core Framework (`core/`)

- `config.py` — Pydantic Settings: single source of truth for all env vars. No longer has Neon/per-agent fields; includes `agents_config: str` pointing to the YAML agent definitions file
- `server.py` — `serve_agent()` helper: starts any Strands agent as an A2A server with auth, CORS, structured logging, and tracing. Also contains `create_mcp_agent()`, `serve_mcp_agent()`, `load_agents_config()`. All specialist agents use this instead of duplicating server boilerplate.
- `schemas.py` — Pydantic models: `Conversation`, `ConversationStatus`, `ConversationSummary`, `MessageRequest`, `Message`, `ActivityEvent`, `ErrorResponse`, `HealthResponse`
- `store.py` — `ConversationStore` protocol + `InMemoryConversationStore` (swap via `STORE_BACKEND` env var)
- `log_stream.py` — SSE broadcaster for real-time log streaming
- `auth.py` — `AgentAuthMiddleware`: X-Agent-API-Key validation on A2A agents (no-op when key is empty; always exempt: `/.well-known/agent-card.json`, `/health`, `/ready`)
- `logging.py` — Structured JSON logging with correlation fields
- `task_store.py` — Thread-safe in-memory A2A TaskStore (swap for Redis/DynamoDB in multi-replica deployments)
- `tracing.py` — OpenTelemetry OTLP setup (no-op when endpoint not configured)
- `mcp.py` — Generic MCP client factory + connection registry
- `safety.py` — LLM-based safety reviewer for destructive operations
- `model.py` — Shared Gemini model factory (`create_model()`)
- `orchestrator.py` — FastAPI orchestrator app

### Model Configuration (`core/model.py`)

All agents share `create_model()` which returns a `GeminiModel`. Uses `GOOGLE_API_KEY` for local dev (Google AI Studio) or Vertex AI via ADC when `GOOGLE_CLOUD_PROJECT` is set.

## Testing Patterns

- All tests mock LLM and database calls completely — no real API keys needed
- `conftest.py` sets env vars at import time (before `Settings()` singleton is created) and also via `monkeypatch` per-test
- Two fixture variants: `mock_agents` (safety reviewer REJECTS) and `mock_agents_approve` (safety reviewer APPROVES)
- Agent mock patches `core.server.create_mcp_agent`; uses `MagicMock` (not `AsyncMock`) because `Agent.__call__` is synchronous, dispatched via `asyncio.to_thread`
- Test YAML config is written to a temp file and pointed to via `AGENTS_CONFIG`
- Agent singleton is reset between tests via `_reset_agent` fixture
- Async tests run automatically via `pytest-asyncio` with `asyncio_mode = "auto"`

## Configuration

All configuration flows through `core/config.py` (Pydantic Settings) and `.env`. Copy `.env.example` to `.env` for local development. Required vars: `AGENTS_CONFIG` (path to `agents.yaml`, defaults to `agents.yaml`), and either `GOOGLE_API_KEY` or `GOOGLE_CLOUD_PROJECT`. MCP server credentials (API keys, project IDs, etc.) are referenced by `agents.yaml` auth blocks and should be set as env vars.

## Code Style

- Python 3.11+, line length 100
- Ruff for linting/formatting (config in `pyproject.toml`)
- Mypy strict mode (excludes tests)
- Known first-party packages for import sorting: `core`, `agents`, `db`
- Ruff rule sets: `E`, `F`, `W`, `I`, `UP`, `B`, `C4`, `SIM`
- Ruff ignores: `B008` (FastAPI `Depends()` pattern), `UP007` (keep `Optional[]` over `X | Y`)
- `TCH` rules intentionally excluded — causes false positives with Protocol definitions and Pydantic models
