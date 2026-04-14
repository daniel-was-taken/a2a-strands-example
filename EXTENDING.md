# Extending the Framework

This guide covers the supported extension points in the repository. Keep the split clear:

- `core/` is the framework runtime
- `agents/` is where you add or modify specialist agents
- `agents.yaml` is the registry and startup contract

If you can solve a change by editing `agents.yaml` or adding a new file in `agents/`, do that before
changing `core/`.

## Core Rules

1. Every agent must be declared in `agents.yaml`.
2. Any configured agent can be launched with `python -m core.server --config agents.yaml --agent "<name>"`.
3. MCP agents need no Python module.
4. Custom agents must expose the factory function named by the `factory` field in `agents.yaml`.
5. `run_system.py` starts all configured agents plus the orchestrator in A2A mode.

## Agent Config Contract

Each entry in `agents.yaml` uses one of two types.

### MCP agent

Use this when the agent is just a model plus tools provided by an MCP server.

```yaml
- name: "Analytics Agent"
  type: mcp
  port: 8005
  description: "Queries the analytics warehouse"
  mcp_url: "https://example.com/mcp"
  auth:
    type: bearer
    env_var: ANALYTICS_API_KEY
  tools: ["list_datasets", "run_query"]
  system_prompt: |
    You are an analytics specialist.
    Use the available tools to answer warehouse questions.
  skills:
    - id: analytics
      name: Analytics
      description: "Warehouse queries and summaries"
      tags: [analytics, warehouse]
```

### Custom agent

Use this when you need custom Python logic such as a Graph or Swarm.

```yaml
- name: "BRD Specialist"
  type: custom
  port: 8004
  description: "Drafts BRDs from confirmed evidence"
  module: "agents.brd_specialist"
  factory: "create_agent"
  skills:
    - id: brd-generation
      name: BRD Generation
      description: "Creates BRDs from evidence summaries"
      tags: [brd, requirements]
```

## Adding a New MCP Agent

1. Add the new entry to `agents.yaml`.
2. Add any referenced secrets to `.env`.
3. Start the agent directly with `core.server` or run the full system with `python run_system.py`.
4. Ask the orchestrator what agents are available and verify your new agent appears.

Run just that agent:

```bash
python -m core.server --config agents.yaml --agent "Analytics Agent"
```

## Adding a New Custom Agent

Create a module under `agents/` with a factory function that returns the agent object.

```python
from a2a.types import AgentSkill
from strands import Agent

from core.model import create_model


def create_agent() -> Agent:
    return Agent(
        model=create_model(),
        name="My Specialist",
        description="Handles a narrow workflow",
        system_prompt="You are a specialist for ...",
        callback_handler=None,
    )
```

Register it in `agents.yaml` using the module path and factory name.

```yaml
- name: "My Specialist"
  type: custom
  port: 8006
  description: "Handles a narrow workflow"
  module: "agents.my_specialist"
  factory: "create_agent"
  skills: []
```

Launch it with:

```bash
python -m core.server --config agents.yaml --agent "My Specialist"
```

You do not need to edit `run_system.py` for a new agent. It reads `agents.yaml` dynamically.

## Supported Agent Patterns

### Plain Agent

Use a regular Strands `Agent` for narrow single-step behavior.

Reference: `agents/brd_specialist.py`

### Graph

Use `GraphBuilder` when the workflow has explicit stages or revision loops.

Reference: `agents/graph_reviewer.py`

Typical fit:

- analyze -> implement -> review
- generate -> critique -> revise
- extract -> validate -> publish

### Swarm

Use `Swarm` when you want autonomous handoffs between collaborating roles.

Reference: `agents/research_team.py`

Typical fit:

- research -> draft -> edit
- analyst -> reviewer -> presenter
- planner -> executor -> checker

### Pipeline of Remote Agents

Use remote A2A agents as building blocks inside another workflow when you want to compose agents
from multiple services.

Reference: `examples/pipeline_agent.py`

## When to Change `core/`

Touch the framework only when the change is cross-cutting.

Good reasons:

- new conversation states
- new approval or confirmation paths
- shared routing helpers
- framework-level auth, storage, or observability changes

Poor reasons:

- adding one more specialist agent
- changing one agent prompt
- experimenting with one workflow

## Extending the BRD Workflow

The fetch-to-BRD demo is implemented in `core/orchestrator.py` with these framework concepts:

- `awaiting_brd_confirmation` conversation state
- evidence capture in `evidence_summary`
- delayed BRD generation through `/confirm-evidence`

If you want to add a similar staged workflow, follow the same shape:

1. add a new conversation status in `core/schemas.py`
2. persist any needed temporary fields
3. add clear transition endpoints in `core/orchestrator.py`
4. update the frontend for the new state
5. add targeted orchestrator tests

## Persistence, Auth, and Model Settings

Key settings live in `core/config.py`.

- `DATABASE_MODE=a2a|direct`
- `STORE_BACKEND=memory|postgres`
- `DATABASE_URL=...` for Postgres persistence
- `API_KEY=...` for orchestrator request auth
- `AGENT_API_KEY=...` for inter-agent auth
- `GOOGLE_API_KEY` or `GOOGLE_CLOUD_PROJECT` for Gemini access

## Verification Checklist

When you add or change framework behavior, run:

```bash
pytest tests/test_orchestrator.py tests/unit/test_mcp.py tests/test_store.py
ruff check .
```

When you add a new custom agent, also run the single-agent command once to confirm the config entry,
module path, and factory function line up:

```bash
python -m core.server --config agents.yaml --agent "My Specialist"
```
