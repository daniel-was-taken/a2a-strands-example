# Use Cases

## Use Case Diagram

```mermaid
graph TB
    User([User])

    subgraph System ["A2A Multi-Agent System"]
        subgraph Conversations ["Conversations"]
            UC1[Create Conversation]
            UC2[Send Message]
            UC3[View Conversation History]
            UC4[List Conversations]
            UC5[Delete Conversation]
        end

        subgraph Queries ["Query Handling"]
            UC6[Ask Database Question]
            UC7[Request Multi-Step Analysis]
            UC8[Request Collaborative Research]
        end

        subgraph Safety ["Safety & Approval"]
            UC9[Submit Destructive Query]
            UC10[Approve Destructive Query]
            UC11[Reject Destructive Query]
        end

        subgraph Monitoring ["Monitoring"]
            UC12[Stream Live Logs]
            UC13[Health Check]
        end

        subgraph Admin ["Administration"]
            UC14[Add MCP Agent via YAML]
            UC15[Add Custom Agent via Python]
            UC16[Configure LLM Provider]
            UC17[Switch Persistence Backend]
        end
    end

    User --> UC1
    User --> UC2
    User --> UC3
    User --> UC4
    User --> UC5
    User --> UC9
    User --> UC10
    User --> UC11
    User --> UC12
    User --> UC13

    UC2 -->|includes| UC6
    UC2 -->|includes| UC7
    UC2 -->|includes| UC8
    UC9 -->|extends| UC2

    Admin ~~~ UC14
    Admin ~~~ UC15
    Admin ~~~ UC16
    Admin ~~~ UC17

    classDef usecase fill:#e8f0fe,stroke:#4285f4,color:#1a1a1a
    classDef safety_uc fill:#fce8e6,stroke:#ea4335,color:#1a1a1a
    classDef admin_uc fill:#e6f4ea,stroke:#34a853,color:#1a1a1a
    classDef user fill:#fef7e0,stroke:#fbbc04,color:#1a1a1a

    class UC1,UC2,UC3,UC4,UC5,UC6,UC7,UC8,UC12,UC13 usecase
    class UC9,UC10,UC11 safety_uc
    class UC14,UC15,UC16,UC17 admin_uc
    class User user
```

## Use Case Details

### UC1: Create Conversation

| Field | Description |
|-------|-------------|
| **Actor** | User |
| **Trigger** | User clicks "+ New Chat" or `POST /conversations` |
| **Precondition** | System is running |
| **Flow** | 1. System creates a new Conversation with a unique ID and `active` status<br/>2. System returns the conversation object |
| **Result** | Empty conversation ready to receive messages |

### UC2: Send Message

| Field | Description |
|-------|-------------|
| **Actor** | User |
| **Trigger** | User types a message and hits send, or `POST /conversations/{id}/messages` |
| **Precondition** | Conversation exists and status is `active` |
| **Flow** | 1. Orchestrator loads conversation context (last 20 messages)<br/>2. Resets agent memory and rebuilds from context<br/>3. Checks for destructive keywords<br/>4. If destructive: routes to Safety Review (UC9)<br/>5. If safe: routes to appropriate specialist agent via A2A<br/>6. Saves user message and agent response to conversation |
| **Result** | Agent response displayed to user |

### UC6: Ask Database Question

| Field | Description |
|-------|-------------|
| **Actor** | User (via Send Message) |
| **Trigger** | Message content matches database-related intent |
| **Flow** | 1. Orchestrator routes to Database Agent via A2A<br/>2. Database Agent calls Neon MCP tools (get_database_tables, describe_table_schema, run_sql)<br/>3. MCP server executes against the database<br/>4. Agent formats and returns results |
| **Example** | "Show me all tables in the database" |

### UC7: Request Multi-Step Analysis

| Field | Description |
|-------|-------------|
| **Actor** | User (via Send Message) |
| **Trigger** | Message requires structured multi-step reasoning |
| **Flow** | 1. Orchestrator routes to Graph Reviewer via A2A<br/>2. Graph Reviewer executes: Analyze -> Implement -> Review<br/>3. If review says "needs revision", loops back to Implement (max 5 iterations)<br/>4. Returns final reviewed output |
| **Example** | "Analyze this codebase and suggest improvements" |

### UC8: Request Collaborative Research

| Field | Description |
|-------|-------------|
| **Actor** | User (via Send Message) |
| **Trigger** | Message requires multi-perspective research |
| **Flow** | 1. Orchestrator routes to Research Team via A2A<br/>2. Researcher agent gathers information<br/>3. Hands off to Writer agent to draft content<br/>4. Hands off to Editor agent for review<br/>5. Agents may hand back autonomously (max 10 handoffs) |
| **Example** | "Research the pros and cons of microservices vs monoliths" |

### UC9: Submit Destructive Query

| Field | Description |
|-------|-------------|
| **Actor** | User |
| **Trigger** | Message contains destructive keywords (DELETE, DROP, TRUNCATE, etc.) |
| **Precondition** | Conversation is `active` |
| **Flow** | 1. Orchestrator detects destructive keyword<br/>2. Safety Reviewer LLM evaluates the query<br/>3a. If APPROVE: query executes immediately<br/>3b. If REJECT: conversation status set to `awaiting_approval`<br/>4. User presented with approve/reject options |
| **Result** | Query either executes or waits for human approval |

### UC10: Approve Destructive Query

| Field | Description |
|-------|-------------|
| **Actor** | User |
| **Trigger** | User clicks "Approve" or `POST /conversations/{id}/approve` |
| **Precondition** | Conversation status is `awaiting_approval` |
| **Flow** | 1. Conversation status set to `active`<br/>2. Original query is executed against the database via the Database Agent<br/>3. Result saved to conversation |
| **Result** | Destructive operation completes |

### UC11: Reject Destructive Query

| Field | Description |
|-------|-------------|
| **Actor** | User |
| **Trigger** | User clicks "Reject" or `POST /conversations/{id}/reject` |
| **Precondition** | Conversation status is `awaiting_approval` |
| **Flow** | 1. Conversation status set to `active`<br/>2. Rejection message saved to conversation<br/>3. Original query is NOT executed |
| **Result** | Destructive operation cancelled |

### UC14: Add MCP Agent via YAML

| Field | Description |
|-------|-------------|
| **Actor** | Developer |
| **Trigger** | Need to connect a new MCP service |
| **Flow** | 1. Add entry to `agents.yaml` with name, type, port, mcp_url, auth, system_prompt<br/>2. Set credentials in `.env`<br/>3. Restart system (`python run_system.py`)<br/>4. Orchestrator auto-discovers the new agent |
| **Result** | New agent available for routing, zero Python code written |

### UC15: Add Custom Agent via Python

| Field | Description |
|-------|-------------|
| **Actor** | Developer |
| **Trigger** | Need agent logic beyond MCP (graph workflows, swarms, pipelines) |
| **Flow** | 1. Create Python module in `agents/` with factory function<br/>2. Use `serve_agent()` to handle server boilerplate<br/>3. Register in `agents.yaml` as `type: custom`<br/>4. Add service to `docker-compose.yml` |
| **Result** | Custom agent running as A2A server |
