# A2A Strands Framework Example

Framework and reference implementation for building A2A multi-agent systems with the Strands
Agents SDK. The project gives you a conversation-first orchestrator, YAML-driven agent
registration, safety review for destructive work, and a staged fetch-to-BRD demo flow.

## Problem Statement

The framework is designed for workflows where a single user request needs more than one kind of
agentic behavior:

- fetch real records from a system of record
- route work to the right specialist agent
- pause when a human should confirm evidence or approve risky actions
- turn validated evidence into a structured output such as a business requirements document

Without that structure, teams usually end up with either a single overloaded agent that does too
much unreliably, or multiple disconnected services with no shared conversation model, no approval
path, and no clean way to add new agents.

## What This Repository Provides

- `core/` contains the framework runtime: orchestrator, config, A2A server helpers, schemas,
  persistence, safety review, logging, and tracing.
- `agents/` contains user-customizable specialist agents.
- `agents.yaml` is the source of truth for agent registration.
- `core.server` can launch both MCP-backed and custom agents directly from `agents.yaml`.
- The orchestrator supports two approval-style pauses:
  - destructive query approval
  - evidence confirmation before BRD drafting

## Project Layout

```text
a2a-strands-example/
├── core/                   # Framework runtime
├── agents/                 # Custom agents you can fork and change
├── db/                     # Optional Postgres-backed store
├── docs/                   # Focused architecture and demo guides
├── examples/               # Standalone pattern examples
├── frontend/               # Browser UI
├── agents.yaml             # Agent declarations
├── run_system.py           # Local multi-process launcher
└── .env.example            # Local environment template
```

## Quick Start

This repository is intentionally local-run only. Start it with Python processes from this repo.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Set at least these values in `.env`:

- `GOOGLE_API_KEY` or `GOOGLE_CLOUD_PROJECT`
- any MCP credential referenced by `agents.yaml` such as `NEON_API_KEY`

Start the local A2A system:

```bash
python run_system.py
```

Then open `http://localhost:8000`.

Direct mode is still available when you only want the first MCP agent loaded in-process:

```bash
DATABASE_MODE=direct python run_system.py
```

## Running Individual Agents

Because agent startup is now unified, the same command works for both MCP and custom agents:

```bash
python -m core.server --config agents.yaml --agent "Database Agent"
python -m core.server --config agents.yaml --agent "Graph Reviewer"
python -m core.server --config agents.yaml --agent "BRD Specialist"
python -m core.server --config agents.yaml --agent "Research Team"
```

## Demo Use Case: Fetch Records and Draft a BRD

This repo now includes a staged A2A demo for the workflow:

1. User asks to fetch records and create a BRD.
2. Orchestrator routes the fetch step to the Database Agent.
3. The system returns an evidence summary and pauses in `awaiting_brd_confirmation`.
4. A human confirms the evidence.
5. Orchestrator routes BRD drafting to the BRD Specialist.
6. The draft is reviewed by the Graph Reviewer.
7. The final BRD is returned to the conversation.

There is a step-by-step demo guide in [docs/demo-brd-use-case.md](docs/demo-brd-use-case.md).

## API

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/conversations` | Create a new conversation |
| `GET` | `/conversations` | List conversation summaries |
| `GET` | `/conversations/{id}` | Get one conversation with messages and events |
| `DELETE` | `/conversations/{id}` | Delete a conversation |
| `POST` | `/conversations/{id}/messages` | Send a message |
| `POST` | `/conversations/{id}/approve` | Approve a destructive request |
| `POST` | `/conversations/{id}/reject` | Reject a destructive request |
| `POST` | `/conversations/{id}/confirm-evidence` | Confirm fetched evidence and draft the BRD |
| `POST` | `/conversations/{id}/reject-evidence` | Cancel the BRD workflow after evidence review |
| `GET` | `/logs/stream` | Stream live logs over SSE |
| `GET` | `/health` | Health check |
| `GET` | `/ready` | Readiness check |

Minimal API example:

```bash
curl -X POST http://localhost:8000/conversations

curl -X POST http://localhost:8000/conversations/<id>/messages \
  -H "Content-Type: application/json" \
  -d '{"content": "Fetch records and create a BRD for onboarding issues"}'

curl -X POST http://localhost:8000/conversations/<id>/confirm-evidence
```

## Documentation

- [EXTENDING.md](EXTENDING.md): how to add MCP, Agent, Graph, and Swarm patterns
- [docs/demo-brd-use-case.md](docs/demo-brd-use-case.md): demo script for the fetch-to-BRD flow
- [docs/architecture.md](docs/architecture.md): runtime structure and sequence diagrams

The README is the primary framework guide. Use the other docs only when you need architecture,
extension, or demo-specific detail.

## Development

```bash
pytest
ruff check .
ruff format .
mypy core/ agents/ db/
python run_system.py
```

## Current Reference Agents

- `Database Agent`: MCP-backed data access
- `Graph Reviewer`: structured analyze -> implement -> review workflow
- `BRD Specialist`: mixed-audience BRD drafting from confirmed evidence
- `Research Team`: autonomous swarm for collaborative research and writing
