# Generic MCP Modularisation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hardcoded Neon MCP integration with a YAML-driven architecture where agents are declared in config, making the system adaptable to any MCP server.

**Architecture:** A single `agents.yaml` declares all agents (MCP-backed or custom Python). A generic MCP client connects to any MCP server. The orchestrator and runner discover agents dynamically from the same YAML. The bug where agent cards advertise the wrong URL is fixed as part of this work.

**Tech Stack:** Python 3.11+, Strands Agents SDK, FastAPI, PyYAML, Pydantic Settings

---

## File Structure

### New files
- `agents.yaml` — Declarative agent configuration
- `mcp_client/client.py` — Generic MCP client factory + connection registry
- `agents/mcp_agent.py` — Generic MCP agent factory + CLI entrypoint
- `tests/unit/test_mcp_client.py` — Tests for generic MCP client
- `tests/unit/test_mcp_agent.py` — Tests for generic MCP agent factory
- `tests/unit/test_agents_config.py` — Tests for YAML config loading

### Modified files
- `common/server.py` — Bug fix: derive `http_url` from port when `None`
- `common/config.py` — Remove per-agent and Neon fields, add `agents_config`
- `agents/orchestrator_agent.py` — Dynamic agent discovery from YAML
- `run_system.py` — Dynamic agent spawning from YAML
- `pyproject.toml` — Add `pyyaml` dependency
- `docker-compose.yml` — Mount `agents.yaml`, simplify env vars
- `.env.example` — Remove Neon-specific vars, add `AGENTS_CONFIG`
- `tests/conftest.py` — Update mocks for new architecture
- `tests/test_orchestrator.py` — Update imports (no functional changes)
- `tests/integration/test_a2a_server.py` — Rewrite to use generic MCP agent
- `tests/integration/test_agent_card.py` — Rewrite to use generic MCP agent

### Deleted files
- `mcp_client/neon_mcp.py`
- `tools/assistant_factory.py`
- `tools/schema_assistant.py`
- `tools/insert_assistant.py`
- `tools/delete_assistant.py`
- `agents/db_agent.py`

---

### Task 1: Fix the Agent Card URL Bug

**Files:**
- Modify: `common/server.py:46-52`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_server_url.py`:

```python
"""Test that serve_agent derives correct http_url from port."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_a2a_server_receives_derived_url_when_http_url_is_none():
    """When http_url is None, A2AServer should receive http://127.0.0.1:{port}/."""
    with (
        patch("common.server.configure_logging"),
        patch("common.server.configure_tracing"),
        patch("common.server.A2AServer") as mock_a2a,
        patch("common.server.uvicorn"),
    ):
        mock_a2a.return_value.to_fastapi_app.return_value = MagicMock()

        from common.server import serve_agent

        serve_agent(MagicMock(), name="test", port=8001)

        mock_a2a.assert_called_once()
        call_kwargs = mock_a2a.call_args[1]
        assert call_kwargs["http_url"] == "http://127.0.0.1:8001/"


def test_a2a_server_uses_explicit_http_url():
    """When http_url is provided, A2AServer should use it as-is."""
    with (
        patch("common.server.configure_logging"),
        patch("common.server.configure_tracing"),
        patch("common.server.A2AServer") as mock_a2a,
        patch("common.server.uvicorn"),
    ):
        mock_a2a.return_value.to_fastapi_app.return_value = MagicMock()

        from common.server import serve_agent

        serve_agent(
            MagicMock(), name="test", port=8001, http_url="https://api.example.com/"
        )

        call_kwargs = mock_a2a.call_args[1]
        assert call_kwargs["http_url"] == "https://api.example.com/"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_server_url.py -v`
Expected: `test_a2a_server_receives_derived_url_when_http_url_is_none` FAILS because `http_url` is passed as `None`.

- [ ] **Step 3: Fix the bug in `common/server.py`**

In `common/server.py`, change line 48 from:

```python
        http_url=http_url,
```

to:

```python
        http_url=http_url or f"http://127.0.0.1:{port}/",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_server_url.py -v`
Expected: Both tests PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `pytest tests/ -v`
Expected: All existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add common/server.py tests/unit/test_server_url.py
git commit -m "fix: derive agent card URL from port when http_url is None"
```

---

### Task 2: Add PyYAML Dependency and Create `agents.yaml`

**Files:**
- Modify: `pyproject.toml`
- Create: `agents.yaml`

- [ ] **Step 1: Add `pyyaml` to `pyproject.toml` dependencies**

In `pyproject.toml`, add `"pyyaml>=6.0"` to the `dependencies` list:

```toml
dependencies = [
    "strands-agents[a2a,gemini]>=1.32.0,<2.0.0",
    "strands-agents-tools>=0.1.0",
    "a2a-sdk>=0.2.0",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "httpx>=0.28.0",
    "pydantic-settings>=2.6.0",
    "python-dotenv>=1.0.0",
    "psycopg2-binary>=2.9.0",
    "slowapi>=0.1.9",
    "botocore[crt]",
    "pyyaml>=6.0",
]
```

- [ ] **Step 2: Install updated dependencies**

Run: `pip install -e ".[dev]"`
Expected: Installs successfully with `pyyaml`.

- [ ] **Step 3: Create `agents.yaml`**

Create `agents.yaml` at project root:

```yaml
agents:
  # ── MCP-backed agents (no code needed) ─────────────────────────────────────
  - name: "Database Reader"
    type: mcp
    port: 8001
    description: "Read-only database access: schema inspection and SELECT queries"
    mcp_url: "https://mcp.neon.tech/mcp"
    auth:
      type: bearer
      env_var: NEON_API_KEY
    tools: ["get_database_tables", "describe_table_schema", "run_sql"]
    system_prompt: |
      You are DatabaseReader, a read-only database assistant.

      Use the available MCP tools to execute read-only SELECT queries and
      retrieve schema information. Only run SELECT queries. Never modify data.

      Consider tables from all user-defined schemas.
      Ignore system/internal schemas (pg_catalog, information_schema, etc.).
      Always query the actual database. Never fabricate schema information.
    skills:
      - id: schema-query
        name: Schema Query
        description: "Inspect database schema and run read-only SELECT queries"
        tags: [database, schema, read-only]

  - name: "Database Writer"
    type: mcp
    port: 8003
    description: "Write operations: INSERT records into database tables"
    mcp_url: "https://mcp.neon.tech/mcp"
    auth:
      type: bearer
      env_var: NEON_API_KEY
    tools: ["get_database_tables", "describe_table_schema", "run_sql"]
    system_prompt: |
      You are DatabaseWriter, responsible for INSERT operations.

      You may inspect schema details before inserting data.
      Only perform INSERT operations or read-only checks needed to support an insert.
      Do not update, delete, alter, create, or drop database objects.

      Consider tables from all user-defined schemas.
      Ignore system/internal schemas (pg_catalog, information_schema, etc.).
      Always query the actual database. Never fabricate schema information.
    skills:
      - id: data-insert
        name: Data Insert
        description: "Insert records into database tables"
        tags: [database, insert, write]

  - name: "Database Deleter"
    type: mcp
    port: 8004
    description: "Delete operations: remove records from database tables (requires prior safety approval)"
    mcp_url: "https://mcp.neon.tech/mcp"
    auth:
      type: bearer
      env_var: NEON_API_KEY
    tools: ["get_database_tables", "describe_table_schema", "run_sql"]
    system_prompt: |
      You are DatabaseDeleter, responsible for DELETE operations.

      You may inspect schema details before deleting data.
      Only perform DELETE operations or read-only checks needed to support a delete.
      Do not insert, update, alter, create, or drop database objects.

      Consider tables from all user-defined schemas.
      Ignore system/internal schemas (pg_catalog, information_schema, etc.).
      Always query the actual database. Never fabricate schema information.
    skills:
      - id: data-delete
        name: Data Delete
        description: "Delete records from database tables (requires prior safety approval)"
        tags: [database, delete, write]

  # ── Custom agents (Python factory) ─────────────────────────────────────────
  - name: "Graph Agent"
    type: custom
    port: 8002
    description: "Multi-step reasoning workflows with analyze, implement, and review stages"
    module: "agents.graph_agent"
    factory: "create_graph_agent"
    skills:
      - id: multi-step-reasoning
        name: Multi-Step Reasoning
        description: "Analyze, implement, and review through a structured graph workflow"
        tags: [reasoning, analysis, implementation, review]
```

- [ ] **Step 4: Write test for YAML loading**

Create `tests/unit/test_agents_config.py`:

```python
"""Tests for agents.yaml config loading."""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml


def _write_config(tmp_path: Path, config: dict) -> Path:
    """Write a YAML config to a temp file and return the path."""
    config_path = tmp_path / "agents.yaml"
    config_path.write_text(yaml.dump(config))
    return config_path


def test_load_valid_agents_config(tmp_path):
    """Valid agents.yaml should parse correctly."""
    config = {
        "agents": [
            {
                "name": "Test Agent",
                "type": "mcp",
                "port": 9001,
                "mcp_url": "https://example.com/mcp",
                "tools": ["tool_a"],
                "system_prompt": "You are a test agent.",
                "skills": [
                    {
                        "id": "test-skill",
                        "name": "Test",
                        "description": "A test skill",
                        "tags": ["test"],
                    }
                ],
            },
        ]
    }
    config_path = _write_config(tmp_path, config)
    loaded = yaml.safe_load(config_path.read_text())
    assert len(loaded["agents"]) == 1
    assert loaded["agents"][0]["name"] == "Test Agent"
    assert loaded["agents"][0]["type"] == "mcp"


def test_load_custom_agent_config(tmp_path):
    """Custom agent entries should have module and factory fields."""
    config = {
        "agents": [
            {
                "name": "Custom Agent",
                "type": "custom",
                "port": 9002,
                "module": "agents.graph_agent",
                "factory": "create_graph_agent",
                "skills": [],
            },
        ]
    }
    config_path = _write_config(tmp_path, config)
    loaded = yaml.safe_load(config_path.read_text())
    agent = loaded["agents"][0]
    assert agent["type"] == "custom"
    assert agent["module"] == "agents.graph_agent"
    assert agent["factory"] == "create_graph_agent"


def test_load_agents_config_with_auth(tmp_path):
    """Auth block should be parsed correctly."""
    config = {
        "agents": [
            {
                "name": "Auth Agent",
                "type": "mcp",
                "port": 9003,
                "mcp_url": "https://example.com/mcp",
                "auth": {"type": "bearer", "env_var": "MY_TOKEN"},
                "tools": ["tool_a"],
                "skills": [],
            },
        ]
    }
    config_path = _write_config(tmp_path, config)
    loaded = yaml.safe_load(config_path.read_text())
    agent = loaded["agents"][0]
    assert agent["auth"]["type"] == "bearer"
    assert agent["auth"]["env_var"] == "MY_TOKEN"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/test_agents_config.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml agents.yaml tests/unit/test_agents_config.py
git commit -m "feat: add agents.yaml config and pyyaml dependency"
```

---

### Task 3: Create Generic MCP Client (`mcp_client/client.py`)

**Files:**
- Create: `mcp_client/client.py`
- Create: `tests/unit/test_mcp_client.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_mcp_client.py`:

```python
"""Tests for the generic MCP client factory and connection registry."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_create_mcp_client_no_auth():
    """create_mcp_client without auth should create client with no auth headers."""
    with patch("mcp_client.client.streamable_http_client") as mock_stream:
        from mcp_client.client import create_mcp_client

        client = create_mcp_client("https://example.com/mcp")
        assert client is not None


def test_create_mcp_client_bearer_auth(monkeypatch):
    """create_mcp_client with bearer auth should read token from env."""
    monkeypatch.setenv("MY_TOKEN", "secret-123")
    with patch("mcp_client.client.streamable_http_client"):
        from mcp_client.client import create_mcp_client

        client = create_mcp_client(
            "https://example.com/mcp",
            auth={"type": "bearer", "env_var": "MY_TOKEN"},
        )
        assert client is not None


def test_create_mcp_client_bearer_auth_missing_env():
    """create_mcp_client with bearer auth should raise when env var is missing."""
    import os

    os.environ.pop("MISSING_TOKEN", None)

    with patch("mcp_client.client.streamable_http_client"):
        import pytest

        from mcp_client.client import create_mcp_client

        with pytest.raises(KeyError):
            create_mcp_client(
                "https://example.com/mcp",
                auth={"type": "bearer", "env_var": "MISSING_TOKEN"},
            )


def test_get_mcp_client_creates_and_caches():
    """get_mcp_client should create a client and cache it by URL."""
    mock_client = MagicMock()
    mock_client._background_thread = MagicMock()
    mock_client._background_thread.is_alive.return_value = True

    with patch("mcp_client.client.create_mcp_client", return_value=mock_client):
        from mcp_client.client import _clients, get_mcp_client

        _clients.clear()
        url = "https://example.com/mcp"

        client1 = get_mcp_client(url)
        client2 = get_mcp_client(url)

        assert client1 is client2
        mock_client.start.assert_called_once()


def test_get_mcp_client_reconnects_on_dead_thread():
    """get_mcp_client should reconnect when the background thread is dead."""
    dead_client = MagicMock()
    dead_client._background_thread = MagicMock()
    dead_client._background_thread.is_alive.return_value = False

    new_client = MagicMock()
    new_client._background_thread = MagicMock()
    new_client._background_thread.is_alive.return_value = True

    with patch("mcp_client.client.create_mcp_client", side_effect=[dead_client, new_client]):
        from mcp_client.client import _clients, get_mcp_client

        _clients.clear()
        url = "https://reconnect.example.com/mcp"

        # First call: dead_client is created but found unhealthy, so reconnects
        _clients[url] = dead_client
        result = get_mcp_client(url)
        assert result is new_client


def test_shutdown_all_stops_all_clients():
    """shutdown_all should stop every registered client."""
    client1 = MagicMock()
    client2 = MagicMock()

    from mcp_client.client import _clients, shutdown_all

    _clients.clear()
    _clients["url1"] = client1
    _clients["url2"] = client2

    shutdown_all()

    client1.stop.assert_called_once()
    client2.stop.assert_called_once()
    assert len(_clients) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_mcp_client.py -v`
Expected: FAIL — `mcp_client.client` does not exist yet.

- [ ] **Step 3: Implement `mcp_client/client.py`**

Create `mcp_client/client.py`:

```python
"""Generic MCP client factory and connection registry.

Connects to any MCP server via Streamable HTTP. Clients are cached by URL
and auto-reconnect when the background thread dies.

Usage::

    from mcp_client.client import get_mcp_client, shutdown_all

    client = get_mcp_client("https://mcp.neon.tech/mcp", auth={"type": "bearer", "env_var": "NEON_API_KEY"})
    # ... use client with Strands Agent ...
    shutdown_all()  # at process exit
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import os
import threading

import httpx
from mcp.client.streamable_http import streamable_http_client
from strands.tools.mcp import MCPClient

logger = logging.getLogger(__name__)

_clients: dict[str, MCPClient] = {}
_lock = threading.Lock()
_SENTINEL = object()


def create_mcp_client(mcp_url: str, auth: dict | None = None) -> MCPClient:
    """Create an MCPClient for any MCP server.

    Args:
        mcp_url: The MCP server endpoint URL.
        auth: Optional auth config. Supported types:
              - ``{"type": "bearer", "env_var": "ENV_VAR_NAME"}``
              Raises KeyError if the env var is not set.
    """
    headers: dict[str, str] = {}
    if auth and auth.get("type") == "bearer":
        token = os.environ[auth["env_var"]]
        headers["Authorization"] = f"Bearer {token}"

    return MCPClient(
        lambda: streamable_http_client(
            mcp_url,
            http_client=httpx.AsyncClient(
                timeout=httpx.Timeout(300.0, connect=30.0, read=120.0),
                headers=headers,
            ),
        ),
    )


def _is_healthy(client: MCPClient) -> bool:
    """Return True if the client's background thread is still running."""
    thread = client._background_thread
    return thread is not None and thread.is_alive()


def get_mcp_client(mcp_url: str, auth: dict | None = None) -> MCPClient:
    """Return a live MCPClient for the given URL, creating or reconnecting as needed.

    Clients are cached by URL. Multiple agents sharing the same MCP URL
    reuse one connection.
    """
    with _lock:
        client = _clients.get(mcp_url)
        if client is not None and _is_healthy(client):
            return client

        if client is not None:
            logger.warning("MCP connection lost for %s, reconnecting", mcp_url)
            with contextlib.suppress(Exception):
                client.stop(None, None, None)

        logger.info("Starting MCP connection to %s", mcp_url)
        client = create_mcp_client(mcp_url, auth)
        client.start()
        client._tool_provider_started = True
        client.add_consumer(_SENTINEL)
        _clients[mcp_url] = client
        return client


def shutdown_all() -> None:
    """Gracefully shut down all MCP connections."""
    with _lock:
        for url, client in _clients.items():
            logger.info("Shutting down MCP connection to %s", url)
            try:
                client._consumers.discard(_SENTINEL)
                client.stop(None, None, None)
            except Exception:
                logger.debug("MCP shutdown error for %s (ignored)", url, exc_info=True)
        _clients.clear()


atexit.register(shutdown_all)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_mcp_client.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mcp_client/client.py tests/unit/test_mcp_client.py
git commit -m "feat: add generic MCP client factory with connection registry"
```

---

### Task 4: Create Generic MCP Agent (`agents/mcp_agent.py`)

**Files:**
- Create: `agents/mcp_agent.py`
- Create: `tests/unit/test_mcp_agent.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_mcp_agent.py`:

```python
"""Tests for the generic MCP agent factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


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
        patch("agents.mcp_agent.get_mcp_client", return_value=mock_client),
        patch("agents.mcp_agent.create_model", return_value=mock_model),
        patch("agents.mcp_agent.Agent") as mock_agent_cls,
    ):
        from agents.mcp_agent import create_mcp_agent

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
    """create_mcp_agent should forward auth config to get_mcp_client."""
    mock_client = MagicMock()

    config = {
        "name": "Auth Agent",
        "mcp_url": "https://example.com/mcp",
        "auth": {"type": "bearer", "env_var": "MY_TOKEN"},
    }

    with (
        patch("agents.mcp_agent.get_mcp_client", return_value=mock_client) as mock_get,
        patch("agents.mcp_agent.create_model", return_value=MagicMock()),
        patch("agents.mcp_agent.Agent"),
    ):
        from agents.mcp_agent import create_mcp_agent

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
        patch("agents.mcp_agent.get_mcp_client", return_value=MagicMock()),
        patch("agents.mcp_agent.create_model", return_value=MagicMock()),
        patch("agents.mcp_agent.Agent") as mock_agent_cls,
    ):
        from agents.mcp_agent import create_mcp_agent

        create_mcp_agent(config)

        call_kwargs = mock_agent_cls.call_args[1]
        assert call_kwargs["system_prompt"] == "Use the available tools."


def test_load_agents_config_reads_yaml(tmp_path):
    """load_agents_config should parse agents.yaml and return the agents list."""
    import yaml

    config = {
        "agents": [
            {"name": "A1", "type": "mcp", "port": 9001, "mcp_url": "https://example.com/mcp",
             "tools": [], "skills": []},
        ]
    }
    config_path = tmp_path / "agents.yaml"
    config_path.write_text(yaml.dump(config))

    from agents.mcp_agent import load_agents_config

    agents = load_agents_config(str(config_path))
    assert len(agents) == 1
    assert agents[0]["name"] == "A1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_mcp_agent.py -v`
Expected: FAIL — `agents.mcp_agent` does not exist yet.

- [ ] **Step 3: Implement `agents/mcp_agent.py`**

Create `agents/mcp_agent.py`:

```python
"""Generic MCP Agent -- serves any MCP-backed agent as an A2A server.

Reads agent config from agents.yaml and creates a Strands Agent connected
to the specified MCP server. Can be run as a standalone process:

    python -m agents.mcp_agent --config agents.yaml --agent "Database Reader"
"""

from __future__ import annotations

import argparse
import logging

import yaml
from a2a.types import AgentSkill
from strands import Agent

from agents.model import create_model
from mcp_client.client import get_mcp_client

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
    client = get_mcp_client(
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
    from common.server import serve_agent

    agent = create_mcp_agent(agent_config)
    skills = [AgentSkill(**s) for s in agent_config.get("skills", [])]

    serve_agent(
        agent,
        name=agent_config["name"],
        port=agent_config["port"],
        skills=skills,
    )


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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_mcp_agent.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/mcp_agent.py tests/unit/test_mcp_agent.py
git commit -m "feat: add generic MCP agent factory with CLI entrypoint"
```

---

### Task 5: Simplify `common/config.py`

**Files:**
- Modify: `common/config.py`

- [ ] **Step 1: Update `common/config.py`**

Replace the contents of `common/config.py` with:

```python
"""Centralised Pydantic Settings for the entire project.

All environment variables are declared here.  Individual modules import
``settings`` rather than calling ``os.environ.get`` scattered across files,
giving a single source of truth and automatic type coercion.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configurable values for the A2A Orchestrator system."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Orchestrator ──────────────────────────────────────────────────────────
    orchestrator_port: int = 8000
    database_mode: str = "a2a"
    #: Comma-separated list of allowed CORS origins.
    allowed_origins: str = "*"
    #: When non-empty, the orchestrator validates this key on every request.
    api_key: str = ""
    rate_limit: str = "30/minute"
    #: Path to the agents YAML config file.
    agents_config: str = "agents.yaml"

    # ── Gemini Model ──────────────────────────────────────────────────────────
    google_api_key: str | None = None
    google_cloud_project: str | None = None
    google_cloud_location: str = "us-central1"
    gemini_model_id: str = "gemini-2.5-flash"

    # ── Query Store ───────────────────────────────────────────────────────────
    store_backend: str = "memory"
    database_url: str | None = None

    # ── Agent-to-Agent Auth ───────────────────────────────────────────────────
    #: Shared secret for inter-agent calls (X-Agent-API-Key header).
    #: When set, every A2AServer validates this header.
    #: Leave empty to disable auth (local dev only).
    agent_api_key: str = ""


settings = Settings()
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: Some tests may fail because `conftest.py` sets env vars for removed Neon fields. These will be fixed in Task 7. The config module itself should load fine since `extra="ignore"` allows unknown env vars.

- [ ] **Step 3: Commit**

```bash
git add common/config.py
git commit -m "refactor: simplify config by removing per-agent and Neon-specific fields"
```

---

### Task 6: Update Orchestrator for Dynamic Agent Discovery

**Files:**
- Modify: `agents/orchestrator_agent.py`

- [ ] **Step 1: Update `agents/orchestrator_agent.py`**

Replace the agent discovery and system prompt logic. The key changes are:

1. Remove hardcoded `_A2A_SYSTEM_PROMPT` with static URLs
2. Add `_load_agents_config()` and `_build_system_prompt()` functions
3. Update `_get_agent()` to build URL list from YAML
4. Update `_AGENT_NAMES` to be built dynamically
5. Remove the `database_agent_url` / `graph_agent_url` imports

Replace lines 1-65 (imports through system prompt) with:

```python
"""Orchestrator Agent -- FastAPI app on port 8000.

Receives user requests via REST and forwards them to specialist agents
discovered from agents.yaml. Includes a safety review step for destructive queries.
"""

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import token_hex
from uuid import uuid4

import yaml
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import StreamingResponse
from strands import Agent

from agents.model import create_model
from common.config import settings
from common.log_stream import broadcaster
from common.log_stream import install as install_sse_handler
from common.schemas import (
    ActivityEvent,
    ErrorResponse,
    HealthResponse,
    Message,
    QueryRequest,
    QueryResponse,
    RequestStatus,
)
from common.store import query_store
from tools.safety_reviewer import create_safety_reviewer, review_delete_request

logger = logging.getLogger(__name__)

DESTRUCTIVE_KEYWORDS = {"delete", "remove", "drop", "truncate", "destroy"}

MAX_THREAD_MESSAGES = 20


def _load_agents_config() -> list[dict]:
    """Load agents list from the YAML config file."""
    with open(settings.agents_config) as f:
        return yaml.safe_load(f)["agents"]


def _build_agent_urls(agents_config: list[dict]) -> list[str]:
    """Build the list of agent URLs from config."""
    return [f"http://localhost:{cfg['port']}/" for cfg in agents_config]


def _build_agent_names(agents_config: list[dict]) -> dict[str, str]:
    """Build URL -> display name mapping from config."""
    return {
        f"http://localhost:{cfg['port']}/": cfg["name"]
        for cfg in agents_config
    }


def _build_system_prompt(agents_config: list[dict]) -> str:
    """Build the orchestrator system prompt dynamically from agents config."""
    agent_lines = []
    for cfg in agents_config:
        url = f"http://localhost:{cfg['port']}/"
        desc = cfg.get("description", cfg["name"])
        agent_lines.append(f'- **{cfg["name"]}** (target_agent_url: "{url}")\n  {desc}')

    agents_block = "\n\n".join(agent_lines)
    return f"""You are the Orchestrator Agent. You receive requests from users and route them
to the appropriate specialist agent using the a2a_send_message tool.

Available agents (use these EXACT URLs with a2a_send_message):

{agents_block}

IMPORTANT: When calling a2a_send_message, you MUST use the exact target_agent_url
values listed above. Do NOT invent or guess URLs.

When asked what agents are available, list all connected agents and their capabilities.
Keep responses clear and relay the results back accurately.
"""
```

Replace the `_get_agent()` function (lines 73-96) with:

```python
def _get_agent() -> Agent:
    """Return the lazily initialised orchestrator agent singleton."""
    global _agent
    if _agent is not None:
        return _agent
    with _agent_lock:
        if _agent is not None:
            return _agent
        if settings.database_mode == "a2a":
            from strands_tools.a2a_client import A2AClientToolProvider

            agents_config = _load_agents_config()
            known_urls = _build_agent_urls(agents_config)
            provider = A2AClientToolProvider(known_agent_urls=known_urls)
            _agent = Agent(
                model=create_model(),
                system_prompt=_build_system_prompt(agents_config),
                tools=provider.tools,
            )
        else:
            from agents.mcp_agent import create_mcp_agent, load_agents_config

            agents_config = load_agents_config(settings.agents_config)
            mcp_agents = [a for a in agents_config if a["type"] == "mcp"]
            if mcp_agents:
                _agent = create_mcp_agent(mcp_agents[0])
            else:
                raise RuntimeError("No MCP agents found in config for direct mode")
        return _agent
```

Replace the static `_AGENT_NAMES` dict (lines 178-182) and `_extract_routed_agents` function with:

```python
def _extract_routed_agents(agent: Agent) -> list[str]:
    """Inspect agent messages to find which A2A agents were called."""
    try:
        agents_config = _load_agents_config()
        agent_names = _build_agent_names(agents_config)
    except Exception:
        agent_names = {}

    agents_used = []
    for msg in reversed(agent.messages):
        for block in msg.get("content", []):
            if isinstance(block, dict) and "toolUse" in block:
                tool = block["toolUse"]
                if tool.get("name") == "a2a_send_message":
                    url = tool.get("input", {}).get("target_agent_url", "")
                    name = agent_names.get(url, url)
                    if name not in agents_used:
                        agents_used.append(name)
    return agents_used
```

Update the `serve()` function (lines 418-433) to remove hardcoded URL logging:

```python
def serve():
    """Start the Orchestrator Agent FastAPI server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logger.info(
        "Starting Orchestrator Agent on port %d (mode=%s)",
        settings.orchestrator_port,
        settings.database_mode,
    )
    if settings.database_mode == "a2a":
        try:
            agents_config = _load_agents_config()
            for cfg in agents_config:
                logger.info("  %s -> http://localhost:%d/", cfg["name"], cfg["port"])
        except Exception:
            logger.warning("Could not load agents config for logging")
    uvicorn.run(app, host="0.0.0.0", port=settings.orchestrator_port)
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: Orchestrator tests will fail because `conftest.py` still patches `agents.db_agent.create_database_agent`. This is fixed in Task 7.

- [ ] **Step 3: Commit**

```bash
git add agents/orchestrator_agent.py
git commit -m "refactor: orchestrator discovers agents dynamically from agents.yaml"
```

---

### Task 7: Update Tests and Conftest

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/test_orchestrator.py` (import check only)

- [ ] **Step 1: Update `tests/conftest.py`**

Replace the entire file with:

```python
"""Configuration and fixtures for tests.

Run:  pytest tests/ -v
"""

import os
import tempfile
from pathlib import Path

# Set test defaults BEFORE any module imports trigger Settings() creation.
os.environ.setdefault("DATABASE_MODE", "direct")
os.environ.setdefault("GOOGLE_API_KEY", "test-google-key")

from unittest.mock import MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient


# ── Test agents.yaml ─────────────────────────────────────────────────────────

_TEST_AGENTS_CONFIG = {
    "agents": [
        {
            "name": "Test MCP Agent",
            "type": "mcp",
            "port": 9001,
            "description": "Test database agent",
            "mcp_url": "https://example.com/mcp",
            "tools": ["tool_a"],
            "system_prompt": "You are a test agent.",
            "skills": [
                {
                    "id": "test-skill",
                    "name": "Test",
                    "description": "A test skill",
                    "tags": ["test"],
                }
            ],
        },
    ]
}

# Write test config to a temp file at import time so settings can reference it.
_test_config_dir = tempfile.mkdtemp()
_test_config_path = str(Path(_test_config_dir) / "agents.yaml")
Path(_test_config_path).write_text(yaml.dump(_TEST_AGENTS_CONFIG))
os.environ.setdefault("AGENTS_CONFIG", _test_config_path)


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch):
    """Ensure required env vars are set for tests (runtime reads)."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("DATABASE_MODE", "direct")
    monkeypatch.setenv("AGENTS_CONFIG", _test_config_path)


@pytest.fixture(autouse=True)
def _clear_store():
    """Reset the in-memory store between tests."""
    from common.store import query_store

    query_store._records.clear()


@pytest.fixture(autouse=True)
def _reset_agent():
    """Reset the lazy-loaded agent singleton between tests."""
    import agents.orchestrator_agent as orch

    orch._agent = None
    yield
    orch._agent = None


def _make_mock_agents(review_return):
    """Shared helper to build mock patches with a given review_delete_request return."""
    mock_agent = MagicMock(return_value="Test agent response")
    mock_agent.messages = []

    mock_model = MagicMock()
    mock_client = MagicMock()

    return (
        mock_agent,
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
    )


@pytest.fixture()
def mock_agents():
    """Patch with safety reviewer that REJECTS destructive queries."""
    mock_agent, *patches = _make_mock_agents((False, "REJECT: test rejection"))
    with patches[0], patches[1], patches[2], patches[3]:
        yield mock_agent


@pytest.fixture()
def mock_agents_approve():
    """Patch with safety reviewer that APPROVES destructive queries."""
    mock_agent, *patches = _make_mock_agents((True, "APPROVE: clearly scoped request"))
    with patches[0], patches[1], patches[2], patches[3]:
        yield mock_agent


@pytest.fixture()
def client(mock_agents):
    """TestClient with fully mocked backend (safety reviewer rejects)."""
    from agents.orchestrator_agent import app

    yield TestClient(app)


@pytest.fixture()
def client_approve(mock_agents_approve):
    """TestClient with fully mocked backend (safety reviewer approves)."""
    from agents.orchestrator_agent import app

    yield TestClient(app)
```

- [ ] **Step 2: Run orchestrator tests**

Run: `pytest tests/test_orchestrator.py -v`
Expected: All orchestrator tests PASS. No changes to `test_orchestrator.py` needed — the test code itself is unchanged; only the mock setup in conftest changed.

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v`
Expected: Most tests pass. Integration tests (`tests/integration/`) may still fail due to `agents.db_agent` imports — fixed in Task 8.

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py
git commit -m "refactor: update test fixtures for generic MCP agent architecture"
```

---

### Task 8: Update Integration Tests

**Files:**
- Modify: `tests/integration/test_a2a_server.py`
- Modify: `tests/integration/test_agent_card.py`

- [ ] **Step 1: Rewrite `tests/integration/test_a2a_server.py`**

Replace the entire file with:

```python
"""Integration tests for A2A server request handling.

Starts a generic MCP agent FastAPI app via ASGI transport (no real port) and
sends A2A protocol messages to verify the server handles them correctly.

Run:
    pytest tests/integration/test_a2a_server.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest


@pytest.fixture()
def mock_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("AGENT_API_KEY", "")


@pytest.fixture()
def a2a_app(mock_env):
    """Build a minimal A2AServer FastAPI app for integration testing."""
    mock_model = MagicMock()
    mock_client = MagicMock()

    with (
        patch("agents.model.create_model", return_value=mock_model),
        patch("mcp_client.client.get_mcp_client", return_value=mock_client),
        patch("common.logging_setup.configure_logging"),
        patch("common.tracing.configure_tracing"),
    ):
        from a2a.types import AgentSkill
        from strands.multiagent.a2a import A2AServer

        from agents.mcp_agent import create_mcp_agent
        from common.task_store import InMemoryA2ATaskStore

        agent_config = {
            "name": "Test Agent",
            "mcp_url": "https://example.com/mcp",
            "description": "Test database agent",
            "system_prompt": "You are a test agent.",
        }
        agent = create_mcp_agent(agent_config)
        server = A2AServer(
            agent=agent,
            http_url="http://127.0.0.1:9001/",
            version="1.0.0",
            skills=[
                AgentSkill(
                    id="test-skill",
                    name="Test Skill",
                    description="A test skill",
                    tags=["test"],
                )
            ],
            task_store=InMemoryA2ATaskStore(),
        )
        return server.to_fastapi_app()


@pytest.mark.asyncio
async def test_agent_card_accessible(a2a_app):
    """AgentCard endpoint must respond 200 without auth."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=a2a_app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/.well-known/agent-card.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "Test Agent"


@pytest.mark.asyncio
async def test_send_message_invalid_body_returns_jsonrpc_error(a2a_app):
    """POST / with invalid JSON should return a JSON-RPC parse error."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=a2a_app),
        base_url="http://test",
    ) as client:
        resp = await client.post("/", content=b"not-json")
    assert resp.status_code == 200
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == -32700


@pytest.mark.asyncio
async def test_auth_middleware_blocks_without_key():
    """When AGENT_API_KEY is set, requests without the header are rejected."""
    mock_model = MagicMock()
    mock_client = MagicMock()

    with (
        patch("agents.model.create_model", return_value=mock_model),
        patch("mcp_client.client.get_mcp_client", return_value=mock_client),
    ):
        from a2a.types import AgentSkill
        from strands.multiagent.a2a import A2AServer

        from agents.mcp_agent import create_mcp_agent
        from common.auth import AgentAuthMiddleware
        from common.task_store import InMemoryA2ATaskStore

        agent = create_mcp_agent({
            "name": "Auth Test Agent",
            "mcp_url": "https://example.com/mcp",
        })
        server = A2AServer(
            agent=agent,
            http_url="http://127.0.0.1:9001/",
            version="1.0.0",
            skills=[AgentSkill(id="t", name="T", description="t", tags=["t"])],
            task_store=InMemoryA2ATaskStore(),
        )
        app = server.to_fastapi_app()
        app.add_middleware(AgentAuthMiddleware, api_key="secret-key")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.post("/", json={})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_middleware_allows_agent_card_without_key():
    """AgentCard endpoint must be accessible even when auth is enabled."""
    mock_model = MagicMock()
    mock_client = MagicMock()

    with (
        patch("agents.model.create_model", return_value=mock_model),
        patch("mcp_client.client.get_mcp_client", return_value=mock_client),
    ):
        from a2a.types import AgentSkill
        from strands.multiagent.a2a import A2AServer

        from agents.mcp_agent import create_mcp_agent
        from common.auth import AgentAuthMiddleware
        from common.task_store import InMemoryA2ATaskStore

        agent = create_mcp_agent({
            "name": "Auth Card Test",
            "mcp_url": "https://example.com/mcp",
        })
        server = A2AServer(
            agent=agent,
            http_url="http://127.0.0.1:9001/",
            version="1.0.0",
            skills=[AgentSkill(id="t", name="T", description="t", tags=["t"])],
            task_store=InMemoryA2ATaskStore(),
        )
        app = server.to_fastapi_app()
        app.add_middleware(AgentAuthMiddleware, api_key="secret-key")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/.well-known/agent-card.json")
    assert resp.status_code == 200
```

- [ ] **Step 2: Rewrite `tests/integration/test_agent_card.py`**

Replace the entire file with:

```python
"""Integration + contract tests for A2A AgentCard endpoints.

These tests build the FastAPI app from a generic MCP agent and validate
the AgentCard JSON schema without needing a real LLM or database.

Run:
    pytest tests/integration/ -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest


@pytest.fixture()
def mock_env(monkeypatch):
    """Minimal env vars required to import agent modules."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("AGENT_API_KEY", "")


@pytest.fixture()
def agent_app(mock_env):
    """Build a generic MCP agent FastAPI app with all external calls mocked."""
    mock_model = MagicMock()
    mock_mcp = MagicMock()

    with (
        patch("agents.model.create_model", return_value=mock_model),
        patch("mcp_client.client.get_mcp_client", return_value=mock_mcp),
        patch("common.logging_setup.configure_logging"),
        patch("common.tracing.configure_tracing"),
    ):
        from a2a.types import AgentSkill
        from strands.multiagent.a2a import A2AServer

        from agents.mcp_agent import create_mcp_agent
        from common.task_store import InMemoryA2ATaskStore

        agent_config = {
            "name": "Test Agent",
            "mcp_url": "https://example.com/mcp",
            "description": "A test agent for integration tests",
            "system_prompt": "You are a test agent.",
        }
        skills = [
            AgentSkill(
                id="test-skill",
                name="Test Skill",
                description="A test skill for integration tests",
                tags=["test"],
            ),
        ]
        agent = create_mcp_agent(agent_config)
        server = A2AServer(
            agent=agent,
            http_url="http://127.0.0.1:9001/",
            version="1.0.0",
            skills=skills,
            task_store=InMemoryA2ATaskStore(),
        )
        return server.to_fastapi_app()


@pytest.mark.asyncio
async def test_agent_card_endpoint_returns_200(agent_app):
    """AgentCard must be served at /.well-known/agent-card.json."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=agent_app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/.well-known/agent-card.json")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_agent_card_is_valid_json(agent_app):
    """AgentCard response must be parseable JSON."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=agent_app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/.well-known/agent-card.json")
    data = resp.json()
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_agent_card_required_fields(agent_app):
    """AgentCard must contain the required A2A spec fields."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=agent_app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/.well-known/agent-card.json")
    card = resp.json()

    required_fields = {"name", "description", "version", "url", "capabilities", "skills"}
    missing = required_fields - set(card.keys())
    assert not missing, f"AgentCard missing required fields: {missing}"


@pytest.mark.asyncio
async def test_agent_card_skills_populated(agent_app):
    """AgentCard skills list must be non-empty and well-formed."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=agent_app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/.well-known/agent-card.json")
    card = resp.json()

    skills = card.get("skills", [])
    assert len(skills) >= 1, "AgentCard must advertise at least one skill"
    for skill in skills:
        assert "id" in skill, "Each skill must have an id"
        assert "name" in skill, "Each skill must have a name"
        assert "description" in skill, "Each skill must have a description"
        assert "tags" in skill, "Each skill must have tags"


@pytest.mark.asyncio
async def test_agent_card_version_is_semver(agent_app):
    """AgentCard version should follow semver (major.minor.patch)."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=agent_app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/.well-known/agent-card.json")
    card = resp.json()
    version = card.get("version", "")
    parts = version.split(".")
    assert len(parts) == 3, f"Version '{version}' is not semver (expected major.minor.patch)"
    assert all(p.isdigit() for p in parts), f"Version parts must be integers: {parts}"
```

- [ ] **Step 3: Run integration tests**

Run: `pytest tests/integration/ -v`
Expected: All integration tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_a2a_server.py tests/integration/test_agent_card.py
git commit -m "refactor: update integration tests for generic MCP agent"
```

---

### Task 9: Update `run_system.py` for Dynamic Agent Spawning

**Files:**
- Modify: `run_system.py`

- [ ] **Step 1: Rewrite `run_system.py`**

Replace the entire file with:

```python
#!/usr/bin/env python3
"""A2A Orchestrator -- System Runner.

Reads agents.yaml and starts all declared agents plus the orchestrator
as separate processes.

Usage:
    python run_system.py                          # A2A mode (default)
    DATABASE_MODE=direct python run_system.py     # Direct mode -- orchestrator only
"""

import importlib
import os
import signal
import subprocess
import sys
import time
import urllib.request

import yaml
from dotenv import load_dotenv

load_dotenv()


def _load_agents_config() -> list[dict]:
    """Load agent definitions from the YAML config."""
    config_path = os.environ.get("AGENTS_CONFIG", "agents.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)["agents"]


def _check_health(port: int, timeout: float = 1.0) -> bool:
    """Return True if the agent-card endpoint responds on the given port."""
    url = f"http://127.0.0.1:{port}/.well-known/agent-card.json"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except Exception:
        return False


def _wait_for_agents(
    processes: list[subprocess.Popen],
    ports: list[int],
    names: list[str],
    timeout: float = 30.0,
) -> bool:
    """Wait until all agents respond to health checks or a process dies."""
    deadline = time.monotonic() + timeout
    ready = [False] * len(ports)

    while time.monotonic() < deadline:
        for i, proc in enumerate(processes):
            if proc.poll() is not None and not ready[i]:
                print(
                    f"\n  ERROR: {names[i]} exited with code {proc.returncode}.",
                    file=sys.stderr,
                )
                print(
                    "  Check the output above for the error.",
                    file=sys.stderr,
                )
                return False

        for i, port in enumerate(ports):
            if not ready[i]:
                ready[i] = _check_health(port)

        if all(ready):
            return True

        time.sleep(0.5)

    for i, r in enumerate(ready):
        if not r:
            print(f"  TIMEOUT: {names[i]} did not respond on port {ports[i]}.", file=sys.stderr)
    return False


def main():
    mode = os.environ.get("DATABASE_MODE", "a2a")
    python = sys.executable
    config_path = os.environ.get("AGENTS_CONFIG", "agents.yaml")

    print("\n=== A2A Orchestrator ===\n")

    if mode == "direct":
        print("Starting system (direct mode -- single process)...")
        print("  Orchestrator -> http://localhost:8000\n")
        os.execvp(python, [python, "-m", "agents.orchestrator_agent"])
        return

    agents_config = _load_agents_config()

    print("Starting system (A2A mode)...")
    for cfg in agents_config:
        print(f"  {cfg['name']:20s} -> http://localhost:{cfg['port']}")
    print(f"  {'Orchestrator':20s} -> http://localhost:8000")
    print()

    # Start agent processes
    agent_procs: list[subprocess.Popen] = []
    agent_names: list[str] = []
    agent_ports: list[int] = []

    for cfg in agents_config:
        if cfg["type"] == "mcp":
            cmd = [python, "-m", "agents.mcp_agent",
                   "--config", config_path, "--agent", cfg["name"]]
        elif cfg["type"] == "custom":
            cmd = [python, "-m", cfg["module"]]
        else:
            print(f"  WARNING: Unknown agent type '{cfg['type']}' for {cfg['name']}, skipping.",
                  file=sys.stderr)
            continue

        agent_procs.append(subprocess.Popen(cmd))
        agent_names.append(cfg["name"])
        agent_ports.append(cfg["port"])

    print("Waiting for agents to start...")
    if not _wait_for_agents(agent_procs, agent_ports, agent_names):
        print(
            "\nAgent startup failed. Shutting down.",
            file=sys.stderr,
        )
        for p in agent_procs:
            p.terminate()
        for p in agent_procs:
            p.wait(timeout=5)
        sys.exit(1)

    print("Agents healthy. Starting orchestrator...\n")

    orch = subprocess.Popen([python, "-m", "agents.orchestrator_agent"])
    all_procs = agent_procs + [orch]

    print("All components started. Send requests to http://localhost:8000/query")
    print("Press Ctrl+C to stop.\n")

    def _shutdown(signum, _frame):
        print("\nShutting down...")
        for p in all_procs:
            p.terminate()
        for p in all_procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        print("Stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while True:
        for i, p in enumerate(all_procs):
            ret = p.poll()
            if ret is not None:
                name = "orchestrator" if p is orch else agent_names[i]
                print(f"\n{name} exited (code {ret}). Shutting down.", file=sys.stderr)
                _shutdown(signal.SIGTERM, None)
        time.sleep(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add run_system.py
git commit -m "refactor: run_system spawns agents dynamically from agents.yaml"
```

---

### Task 10: Delete Old Files

**Files:**
- Delete: `mcp_client/neon_mcp.py`
- Delete: `tools/assistant_factory.py`
- Delete: `tools/schema_assistant.py`
- Delete: `tools/insert_assistant.py`
- Delete: `tools/delete_assistant.py`
- Delete: `agents/db_agent.py`

- [ ] **Step 1: Verify no remaining imports of deleted modules**

Run these grep commands to verify no code references the old modules:

```bash
grep -r "neon_mcp" --include="*.py" . | grep -v __pycache__ | grep -v ".pyc"
grep -r "assistant_factory" --include="*.py" . | grep -v __pycache__ | grep -v ".pyc"
grep -r "schema_assistant" --include="*.py" . | grep -v __pycache__ | grep -v ".pyc"
grep -r "insert_assistant" --include="*.py" . | grep -v __pycache__ | grep -v ".pyc"
grep -r "delete_assistant" --include="*.py" . | grep -v __pycache__ | grep -v ".pyc"
grep -r "from agents.db_agent" --include="*.py" . | grep -v __pycache__ | grep -v ".pyc"
```

Expected: No matches outside of the files being deleted and potentially `test_smoke.py` (which doesn't import them).

- [ ] **Step 2: Delete the files**

```bash
git rm mcp_client/neon_mcp.py
git rm tools/assistant_factory.py
git rm tools/schema_assistant.py
git rm tools/insert_assistant.py
git rm tools/delete_assistant.py
git rm agents/db_agent.py
```

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git commit -m "refactor: remove Neon-specific MCP client and hardcoded tool modules"
```

---

### Task 11: Update `.env.example` and `docker-compose.yml`

**Files:**
- Modify: `.env.example`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Update `.env.example`**

Replace the entire file with:

```bash
# ── Gemini model ───────────────────────────────────────────────────────────────
# Option A: Google AI Studio (simplest for local dev)
GOOGLE_API_KEY=

# Option B: Vertex AI (requires: gcloud auth application-default login)
# GOOGLE_CLOUD_PROJECT=
# GOOGLE_CLOUD_LOCATION=us-central1

# Optional: override the default model
# GEMINI_MODEL_ID=gemini-2.5-flash

# ── Agent config ──────────────────────────────────────────────────────────────
# Path to the agents YAML config file (default: agents.yaml)
# AGENTS_CONFIG=agents.yaml

# ── Architecture mode ──────────────────────────────────────────────────────────
# "a2a" (default): multi-service, orchestrator + specialist A2A servers
# "direct":        single process, first MCP agent loaded in-process
# DATABASE_MODE=a2a

# ── API key authentication (orchestrator) ──────────────────────────────────────
# Leave empty to disable. When set, every request must include X-API-Key header.
# API_KEY=

# ── Agent-to-agent authentication ─────────────────────────────────────────────
# Shared secret for inter-agent calls (X-Agent-API-Key header).
# Must be the same value on all services.  Leave empty to disable.
# AGENT_API_KEY=

# ── Rate limiting (slowapi format) ────────────────────────────────────────────
# RATE_LIMIT=30/minute

# ── CORS origins (comma-separated) ────────────────────────────────────────────
# ALLOWED_ORIGINS=http://localhost:3000,https://your-domain.com

# ── Service ports ─────────────────────────────────────────────────────────────
# ORCHESTRATOR_PORT=8000

# ── Query persistence backend ─────────────────────────────────────────────────
# "memory" (default) or "postgres"
# STORE_BACKEND=memory
# DATABASE_URL=postgres://user:pass@host:5432/dbname

# ── OpenTelemetry (set to enable distributed tracing) ─────────────────────────
# OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317

# ── MCP server credentials (referenced by agents.yaml auth blocks) ────────────
# Add env vars here that your agents.yaml auth.env_var fields reference.
# Example for Neon:
# NEON_API_KEY=
```

- [ ] **Step 2: Update `docker-compose.yml`**

Replace the entire file with:

```yaml
services:
  orchestrator:
    build: .
    command: ["python", "-m", "agents.orchestrator_agent"]
    env_file: .env
    ports:
      - "8000:8000"
    environment:
      DATABASE_MODE: "a2a"
      AGENTS_CONFIG: "/app/agents.yaml"
    volumes:
      - ./agents.yaml:/app/agents.yaml:ro
    depends_on:
      - db-reader
      - db-writer
      - db-deleter
      - graph-agent
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

  db-reader:
    build: .
    command: ["python", "-m", "agents.mcp_agent", "--config", "/app/agents.yaml", "--agent", "Database Reader"]
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

  db-writer:
    build: .
    command: ["python", "-m", "agents.mcp_agent", "--config", "/app/agents.yaml", "--agent", "Database Writer"]
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

  db-deleter:
    build: .
    command: ["python", "-m", "agents.mcp_agent", "--config", "/app/agents.yaml", "--agent", "Database Deleter"]
    env_file: .env
    ports:
      - "8004:8004"
    volumes:
      - ./agents.yaml:/app/agents.yaml:ro
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8004/.well-known/agent-card.json"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

  graph-agent:
    build: .
    command: ["python", "-m", "agents.graph_agent"]
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
```

- [ ] **Step 3: Commit**

```bash
git add .env.example docker-compose.yml
git commit -m "refactor: update env example and docker-compose for YAML-driven agents"
```

---

### Task 12: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md to reflect new architecture**

Key updates:
- Replace "Database Agent" with "MCP Agents (config-driven)"
- Update agent topology diagram to show dynamic agents from YAML
- Update commands section for new agent launching
- Remove references to `agents/db_agent.py`, `tools/assistant_factory.py`, etc.
- Add `agents.yaml` documentation
- Update testing patterns to reference new mock paths

The content should reflect all the changes made in Tasks 1-11. Read the current CLAUDE.md and update each section that references deleted files, changed architecture, or old patterns.

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for YAML-driven agent architecture"
```

---

### Task 13: Run Full Lint + Type Check + Test Suite

**Files:** None (verification only)

- [ ] **Step 1: Run ruff lint**

Run: `ruff check .`
Expected: No errors. Fix any that appear.

- [ ] **Step 2: Run ruff format**

Run: `ruff format .`
Expected: Files formatted (or already formatted).

- [ ] **Step 3: Run mypy**

Run: `mypy agents/ tools/ mcp_client/ common/`
Expected: No new type errors. May need to add `types-PyYAML` to dev dependencies if mypy complains about yaml stubs.

- [ ] **Step 4: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 5: Fix any issues found and commit**

```bash
git add -A
git commit -m "chore: fix lint, type, and test issues from modularisation"
```
