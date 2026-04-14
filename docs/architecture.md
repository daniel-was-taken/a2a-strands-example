# Architecture

## System Overview

```mermaid
graph TB
    User([User / Browser])

    subgraph Orchestrator ["Orchestrator :8000"]
        FE[Frontend]
        API[Conversation API]
        Safety[Safety Review]
        Store[(Conversation Store)]
        Router[A2A Router]
    end

    subgraph Agents ["Configured Agents"]
        DB[Database Agent :8001]
        GR[Graph Reviewer :8002]
        RT[Research Team :8003]
        BRD[BRD Specialist :8004]
    end

    subgraph External ["External Systems"]
        MCP[MCP Server]
        LLM[Gemini]
    end

    User --> FE
    User --> API
    API --> Store
    API --> Safety
    API --> Router
    Router --> DB
    Router --> GR
    Router --> RT
    Router --> BRD
    DB --> MCP
    Orchestrator --> LLM
    GR --> LLM
    RT --> LLM
    BRD --> LLM
```

## Framework Boundary

```mermaid
graph LR
    subgraph Core ["core/"]
        Orch[orchestrator.py]
        Server[server.py]
        Config[config.py]
        Schemas[schemas.py]
        Store[store.py]
        Safety[safety.py]
        MCPClient[mcp.py]
    end

    subgraph Agents ["agents/"]
        Graph[graph_reviewer.py]
        BRDAgent[brd_specialist.py]
        Research[research_team.py]
    end

    YAML[(agents.yaml)] --> Server
    Config --> Orch
    Config --> Server
    Schemas --> Orch
    Store --> Orch
    Safety --> Orch
    MCPClient --> Server
    Server --> Graph
    Server --> BRDAgent
    Server --> Research
```

## Startup Model

- `run_system.py` reads `agents.yaml`
- every configured agent is started through `core.server`
- `core.server` supports both `mcp` and `custom` agent entries
- the orchestrator builds its routing prompt from the same `agents.yaml`

That means `agents.yaml` is the effective runtime contract for local startup and direct agent
launches.

## Standard Request Flow

```mermaid
sequenceDiagram
    actor User
    participant Orch as Orchestrator
    participant Store as Conversation Store
    participant Agent as Specialist Agent

    User->>Orch: POST /conversations/{id}/messages
    Orch->>Store: load conversation context
    Orch->>Orch: rebuild prompt from recent messages
    Orch->>Agent: route over A2A
    Agent-->>Orch: result
    Orch->>Store: save agent reply and events
    Orch-->>User: updated conversation
```

## Destructive Request Flow

```mermaid
sequenceDiagram
    actor User
    participant Orch as Orchestrator
    participant Safety as Safety Reviewer
    participant Store as Conversation Store
    participant Agent as Database Agent

    User->>Orch: destructive request
    Orch->>Safety: review request
    Safety-->>Orch: approve or reject recommendation
    Orch->>Store: set awaiting_approval
    User->>Orch: approve
    Orch->>Agent: execute request
    Agent-->>Orch: result
    Orch->>Store: clear approval fields
    Orch-->>User: updated conversation
```

## Fetch-to-BRD Flow

```mermaid
sequenceDiagram
    actor User
    participant Orch as Orchestrator
    participant DB as Database Agent
    participant BRD as BRD Specialist
    participant Review as Graph Reviewer
    participant Store as Conversation Store

    User->>Orch: "Fetch records and create a BRD"
    Orch->>DB: fetch evidence summary
    DB-->>Orch: structured evidence summary
    Orch->>Store: save evidence_summary
    Orch-->>User: status = awaiting_brd_confirmation
    User->>Orch: confirm evidence
    Orch->>BRD: draft BRD from evidence
    BRD-->>Orch: draft BRD
    Orch->>Review: review and improve draft
    Review-->>Orch: final BRD
    Orch->>Store: clear temporary BRD fields
    Orch-->>User: final BRD response
```

## Key Design Choices

- Conversation context is rebuilt per turn to avoid cross-conversation leakage.
- Approval and evidence confirmation are separate states because they solve different risks.
- Custom and MCP agents share one startup path so the framework stays configuration-driven.
- The BRD flow is staged to keep facts and assumptions separated.
