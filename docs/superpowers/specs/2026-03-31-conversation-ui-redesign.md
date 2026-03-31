# Conversation-First UI Redesign

## Goal

Replace the flat query-list UI with a ChatGPT-style conversation interface, fix agent memory leaking across conversations, and introduce a proper conversation data model that separates chat threads from the safety review/approval workflow.

## Architecture

The orchestrator's data model shifts from query-centric (`QueryResponse` with bolted-on replies) to conversation-centric (`Conversation` with a first-class message thread). The agent singleton is kept but its `messages` array is reset before each turn, with context rebuilt from the conversation's stored messages. The frontend becomes a ChatGPT-style chat app: sidebar with conversations, "New Chat" button, message thread in the main area, inline approval dialogs.

## Tech Stack

- **Frontend:** Vanilla JS (no framework, no build step)
- **Backend:** FastAPI (existing orchestrator)
- **Store:** `ConversationStore` protocol with `InMemoryConversationStore` and `PostgresConversationStore` implementations
- **Agent framework:** Strands Agents SDK (unchanged)

---

## 1. Data Model

### 1.1 Conversation (replaces QueryResponse)

```python
class ConversationStatus(StrEnum):
    ACTIVE = "active"
    AWAITING_APPROVAL = "awaiting_approval"

class Conversation(BaseModel):
    id: str                                     # UUID
    title: str                                  # Auto-generated from first user message (~50 chars)
    status: ConversationStatus = ConversationStatus.ACTIVE
    # Approval fields (only populated when status == AWAITING_APPROVAL)
    approval_id: str | None = None
    review_verdict: str | None = None
    review_recommended_reject: bool = False      # True = safety reviewer recommends rejection
    pending_query: str | None = None             # The destructive query awaiting decision
    # Thread
    messages: list[Message] = []
    events: list[ActivityEvent] = []
    created_at: str
    updated_at: str
```

### 1.2 Message (unchanged)

```python
class Message(BaseModel):
    role: Literal["user", "agent"]
    content: str
    timestamp: str  # ISO 8601, auto-generated
```

### 1.3 MessageRequest (replaces QueryRequest)

```python
class MessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
```

### 1.4 Key behavioral differences from current model

- A conversation never "completes" -- it stays `active` and accepts more messages.
- `COMPLETED`, `FAILED`, `REJECTED`, `RECOMMENDED_REJECT` are no longer statuses. Failures become an agent error message in the thread. Rejections clear the approval state and add an agent message ("Query rejected by user.").
- `RECOMMENDED_REJECT` is captured by `review_recommended_reject: bool` on the conversation, combined with `AWAITING_APPROVAL` status.
- `ActivityEvent` is unchanged (timestamp, agent, action, detail).

### 1.5 Removed models

- `QueryResponse` -- replaced by `Conversation`
- `QueryRequest` -- replaced by `MessageRequest`
- `RequestStatus` enum -- replaced by `ConversationStatus`

---

## 2. API Endpoints

### 2.1 New endpoints (replace all /query* and /queries* endpoints)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/conversations` | Create new empty conversation |
| `GET` | `/conversations` | List all conversations (newest first, messages excluded) |
| `GET` | `/conversations/{id}` | Get conversation with full messages + events |
| `POST` | `/conversations/{id}/messages` | Send a message, process it, return updated conversation |
| `POST` | `/conversations/{id}/approve` | Approve pending destructive query |
| `POST` | `/conversations/{id}/reject` | Reject pending destructive query |
| `DELETE` | `/conversations/{id}` | Delete a conversation |

### 2.2 Unchanged endpoints

- `GET /health` -- health check
- `GET /ready` -- readiness probe
- `GET /logs/stream` -- SSE log stream
- `GET /` -- serve frontend HTML
- `/static` -- serve frontend assets

### 2.3 Removed endpoints

- `POST /query`
- `GET /queries`
- `GET /queries/{request_id}`
- `POST /queries/approve/{approval_id}`
- `POST /queries/reject/{approval_id}`
- `POST /query/{request_id}/reply`

### 2.4 POST /conversations/{id}/messages flow

1. Validate conversation exists and status is `active` (409 if `awaiting_approval`).
2. Add user message to conversation.
3. Check if content contains destructive keywords.
4. **If destructive:** run safety review.
   - If reviewer recommends rejection: set `awaiting_approval`, `review_recommended_reject = True`, store `pending_query`. Return.
   - If reviewer approves: set `awaiting_approval`, `review_recommended_reject = False`, store `pending_query` and `approval_id`. Return.
5. **If safe:** reset agent context, rebuild from conversation messages, execute, add agent response. Return.

### 2.5 POST /conversations/{id}/approve flow

1. Verify conversation is `awaiting_approval` (409 otherwise).
2. Add activity event: "Human approved the query".
3. Reset agent context, rebuild from conversation messages, execute `pending_query`.
4. Add agent response message.
5. Clear approval fields (`approval_id`, `review_verdict`, `review_recommended_reject`, `pending_query`), set status back to `active`.
6. Return updated conversation.

### 2.6 POST /conversations/{id}/reject flow

1. Verify conversation is `awaiting_approval` (409 otherwise).
2. Add activity event: "Human rejected the query".
3. Add agent message: "Query rejected by user."
4. Clear approval fields, set status back to `active`.
5. Return updated conversation.

### 2.7 GET /conversations (list)

Returns a `ConversationSummary` list (not full `Conversation`) for performance:

```python
class ConversationSummary(BaseModel):
    id: str
    title: str
    status: ConversationStatus
    created_at: str
    updated_at: str
```

Messages and events are excluded. Frontend uses this for the sidebar. Full data is fetched via `GET /conversations/{id}` when a conversation is selected.

---

## 3. Store

### 3.1 ConversationStore protocol (replaces QueryStore)

```python
class ConversationStore(Protocol):
    def create(self, conversation: Conversation) -> None: ...
    def get(self, conversation_id: str) -> Conversation | None: ...
    def list_all(self) -> list[Conversation]: ...
    def add_message(self, conversation_id: str, message: Message) -> None: ...
    def add_event(self, conversation_id: str, event: ActivityEvent) -> None: ...
    def update(self, conversation_id: str, **fields) -> Conversation | None: ...
    def delete(self, conversation_id: str) -> None: ...
```

### 3.2 InMemoryConversationStore

Thread-safe dict-backed implementation. Same pattern as current `InMemoryStore` with `threading.Lock`.

### 3.3 PostgresConversationStore

New `conversations` table:

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id                         TEXT PRIMARY KEY,
    title                      TEXT NOT NULL DEFAULT '',
    status                     TEXT NOT NULL DEFAULT 'active',
    approval_id                TEXT,
    review_verdict             TEXT,
    review_recommended_reject  BOOLEAN NOT NULL DEFAULT FALSE,
    pending_query              TEXT,
    messages                   JSONB NOT NULL DEFAULT '[]'::jsonb,
    events                     JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL
);
```

### 3.4 Removed

- `QueryStore` protocol
- `InMemoryStore` class
- `PostgresStore` class
- `get_by_approval_id` method (approval is now looked up by conversation ID)

---

## 4. Agent Context Isolation

### 4.1 The problem

The orchestrator agent is a singleton. Its `messages` array accumulates across all queries. Query 2 sees context from query 1, query 3 sees context from 1 and 2, etc.

### 4.2 The fix

Before every agent call (new message or approved query):

```python
agent = _get_agent()
agent.messages = []  # Clean slate -- no cross-conversation leakage

# Rebuild context from THIS conversation's messages (last 20)
recent = conversation.messages[-MAX_THREAD_MESSAGES:]
if recent:
    context_parts = []
    for msg in recent:
        label = "User" if msg.role == "user" else "Agent"
        context_parts.append(f"{label}: {msg.content}")
    prompt = "Previous conversation:\n" + "\n".join(context_parts)
else:
    prompt = user_input

result = await asyncio.to_thread(agent, prompt)
```

### 4.3 Context cap

`MAX_THREAD_MESSAGES = 20` (existing constant). Only the last 20 messages are sent to the LLM. Older messages are still stored and visible in the UI.

---

## 5. Frontend UI

### 5.1 Layout

ChatGPT-style, vanilla JS, three files: `index.html`, `style.css`, `app.js`.

- **Sidebar** (left): "New Chat" button at top, list of conversations (title + timestamp), active conversation highlighted.
- **Main area** (center): message thread with user messages right-aligned (indigo bubble) and agent messages left-aligned (gray bubble). Auto-scrolls to latest.
- **Input bar** (bottom of main): textarea + Send button, pinned. Disabled with message "Awaiting approval..." when conversation is `awaiting_approval`.
- **Approval dialog**: appears inline at the bottom of the message thread when `awaiting_approval`. Shows safety verdict, Approve/Reject buttons. Different styling for recommended-reject vs approved-but-needs-confirmation.
- **Activity log**: collapsible section within each conversation, below the message thread. Shows agent routing, safety events for that conversation.
- **Live log panel**: kept as-is at bottom of page. System-wide SSE debug stream, dark theme, collapsible.

### 5.2 Behavioral changes

- No polling for conversation list -- fetch on load + after each action.
- Detail polling stays for in-flight messages (stop when agent responds).
- "New Chat" creates conversation via `POST /conversations`, selects it, focuses input.
- All messages go through `POST /conversations/{id}/messages` (no separate submit vs reply paths).
- No status badges in sidebar. Only indicator: small warning icon if `awaiting_approval`.
- Welcome screen shown when no conversation is selected.

### 5.3 Mobile

Same responsive pattern as current: sidebar slides in from left, hamburger menu button, backdrop overlay.

---

## 6. File Change Summary

### Modified

| File | Change |
|------|--------|
| `common/schemas.py` | Replace `QueryResponse`, `QueryRequest`, `RequestStatus` with `Conversation`, `ConversationStatus`, `MessageRequest` |
| `common/store.py` | Replace `QueryStore` + `InMemoryStore` with `ConversationStore` + `InMemoryConversationStore` |
| `db/repository.py` | Replace `PostgresStore` with `PostgresConversationStore`, new table schema |
| `agents/orchestrator_agent.py` | New conversation endpoints, agent context reset, remove old query endpoints |
| `frontend/index.html` | ChatGPT-style layout |
| `frontend/app.js` | Complete rewrite: conversation CRUD, message sending, inline approval |
| `frontend/style.css` | Updated styles for conversation layout |
| `tests/test_orchestrator.py` | Updated for new endpoints and models |
| `tests/test_store.py` | Updated for new store protocol |
| `tests/e2e/test_e2e_stub.py` | Updated for new endpoints |

### Unchanged

| File | Reason |
|------|--------|
| `agents/mcp_agent.py` | Agent creation unaffected |
| `agents/graph_agent.py` | Graph agent unaffected |
| `agents/model.py` | Model config unaffected |
| `mcp_client/client.py` | MCP client unaffected |
| `common/config.py` | No new settings needed |
| `common/server.py` | A2A server helper unaffected |
| `common/auth.py` | Auth middleware unaffected |
| `common/logging_setup.py` | Structured logging unaffected |
| `common/task_store.py` | A2A task store unaffected |
| `common/log_stream.py` | SSE broadcaster unaffected |
| `tools/safety_reviewer.py` | Safety review logic unaffected |
| `agents.yaml` / `agents-docker.yaml` | No changes (future: add `ui_url` for external agents) |
| `docker-compose.yml` / `run_system.py` | No changes |

---

## 7. Future: External Agent Integration

Not in scope for this iteration, but the design is forward-compatible:

- `agents.yaml` can add `type: external` entries with `ui_url` and `protocol` fields.
- The sidebar could show external agents with an icon indicating "opens embedded UI".
- Chat bridge (routing messages to external agents via WebSocket/REST adapters) is a separate project.
