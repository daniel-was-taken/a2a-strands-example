# Development Plan: Production-Ready Refactor + Neon Data API Migration

## Context

This project is an A2A multi-agent orchestrator built with Strands Agents SDK.
It currently uses a Neon MCP server (`mcp.neon.tech/mcp`) as the sole database
integration path. The project must become deployment-ready while keeping MCP as a
generic feature for connecting to **any** MCP server, but replacing the Neon-specific
MCP usage with Neon's **Data API** (HTTP/REST) for direct database access.

---

## 1. Replace Neon MCP with Neon Data API

### 1.1 Create `db/neon.py` — Neon Data API client

Create a thin async-capable HTTP client that talks to the
[Neon serverless driver / Data API](https://neon.tech/docs/serverless/serverless-driver)
or the Neon SQL-over-HTTP endpoint (`https://[project].neon.tech/sql`).

Requirements:
- Use `httpx` (already a dependency) for HTTP calls.
- Accept a Neon connection string or project endpoint + API key from `core/config.py`.
- Expose three operations that mirror the MCP tools the Database Agent currently uses:
  - `get_database_tables()` → `SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema')`
  - `describe_table_schema(schema, table)` → `SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = $1 AND table_name = $2`
  - `run_sql(query)` → execute arbitrary SQL and return rows as JSON
- Parameterise queries properly; never interpolate user input into SQL strings.
- Return results as plain Python dicts/lists (no ORM).

### 1.2 Create `agents/database_agent.py` — custom Database Agent

Convert the Database Agent from a config-only MCP agent to a **custom** agent with
Strands `@tool`-decorated Python functions that call `db/neon.py`.

The agent module should:
- Define `get_database_tables`, `describe_table_schema`, and `run_sql` as `@tool` functions.
- Define a `create_agent()` factory that returns a `strands.Agent` with those tools.
- Use `create_model()` from `core/model.py`.
- Keep the same system prompt currently in `agents.yaml` for the Database Agent.

### 1.3 Update `agents.yaml` — change Database Agent from `mcp` to `custom`

```yaml
- name: "Database Agent"
  type: custom
  port: 8001
  description: "Full database access: schema inspection, SELECT, INSERT, DELETE queries"
  module: "agents.database_agent"
  factory: "create_agent"
  skills:
    - id: database-ops
      name: Database Operations
      description: "Schema inspection and SQL queries"
      tags: [database, sql]
```

### 1.4 Add Neon Data API settings to `core/config.py`

Add to the `Settings` class:

```python
# ── Neon Data API ─────────────────────────────────────────────────────────
neon_api_key: str | None = None
neon_database_url: str | None = None  # The Neon SQL-over-HTTP endpoint or connection string
```

Remove `NEON_API_KEY` from the MCP auth path. It is now consumed directly by `db/neon.py`.

### 1.5 Keep MCP as a generic feature

**Do not delete** `core/mcp.py`, `ReconnectingMCPClient`, or `create_mcp_client`.
The MCP infrastructure stays intact for any other MCP server a user might add
(analytics, CRM, etc.). Only the **Neon-specific usage** is being replaced.

The `agents.yaml` MCP agent type (`type: mcp`) and `core/server.py`'s
`create_mcp_agent()` remain fully functional.

---

## 2. Production-Ready Database Layer

### 2.1 Refactor `db/repository.py` — connection pooling + async

Current problems:
- Opens a new `psycopg2` connection on every single operation (`_get_conn()` call).
- Synchronous `psycopg2` blocks the event loop when called from async FastAPI handlers.
- `_CREATE_TABLE` and `ALTER TABLE` migrations run in `__init__` — fragile for production.

Changes:
- Replace `psycopg2` with `psycopg` (v3) which supports both sync and async, or use
  `asyncpg` for pure async.
- Use a connection pool (`psycopg_pool.AsyncConnectionPool` or `asyncpg.create_pool`).
- Initialise the pool once at startup (in the FastAPI lifespan) and close it on shutdown.
- Move DDL / migrations out of `__init__` into a dedicated `db/migrations.py` or use
  `alembic` if schema evolution is expected.
- Update `pyproject.toml` dependencies accordingly: drop `psycopg2-binary`, add `psycopg[binary,pool]` or `asyncpg`.

### 2.2 Make `PostgresConversationStore` async

The `ConversationStore` protocol in `core/store.py` should become async:

```python
class ConversationStore(Protocol):
    async def create(self, conversation: Conversation) -> None: ...
    async def get(self, conversation_id: str) -> Conversation | None: ...
    async def list_all(self) -> list[Conversation]: ...
    # etc.
```

Both `InMemoryConversationStore` and `PostgresConversationStore` should implement
the async protocol. The in-memory store can use trivial `async def` wrappers.

All callers in `core/orchestrator.py` must `await` store operations (many are
already in `async def` handlers, so this is straightforward).

### 2.3 Environment-driven store selection

`core/store.py` `_create_store()` already selects by `settings.store_backend`.
Keep that pattern. When `store_backend == "postgres"`, ensure the pool is created
from `settings.database_url`. Validate at startup that `database_url` is set when
postgres is selected.

---

## 3. Files and Code to Discard

### 3.1 Delete files

| File | Reason |
|---|---|
| `examples/mcp_agent.py` | Hardcoded Neon MCP URL. No longer relevant since Database Agent is custom. |
| `examples/a2a_graph.py` | Standalone demo script; not part of the runtime. Pattern is already demonstrated in `agents/graph_reviewer.py`. |
| `examples/a2a_swarm.py` | Standalone demo script; not part of the runtime. Pattern is already demonstrated in `agents/research_team.py`. |
| `examples/pipeline_agent.py` | Depends on hardcoded localhost agent URLs. Useful concept but not production code; can be recreated from docs. |
| `docs/presentation/` | Presentation generation script and markdown. Not runtime or dev documentation. |

### 3.2 Remove the `examples/` directory entirely

All four files are standalone demos that duplicate patterns already shown in
`agents/` and `EXTENDING.md`. After deletion, remove any README references
to the examples directory.

### 3.3 Code to remove or clean up

| Location | What | Reason |
|---|---|---|
| `agents.yaml` — Database Agent entry | `mcp_url`, `auth`, `tools` fields | No longer needed; agent becomes `type: custom`. |
| `agents.yaml` — Database Agent entry | `system_prompt` field | Moves into `agents/database_agent.py`. |
| `pyproject.toml` | `psycopg2-binary` dependency | Replaced by `psycopg[binary,pool]` or `asyncpg`. |
| `core/orchestrator.py` | `DATABASE_MODE == "direct"` path in `_get_agent()` | The "direct" mode creates a single MCP agent in-process, bypassing A2A. After migration to custom agents this path is dead code. Remove it and the `database_mode` setting. All usage should go through A2A mode. |
| `run_system.py` | `DATABASE_MODE=direct` fallback | Same as above — remove the direct-mode branch. |
| `core/config.py` | `database_mode` setting | No longer needed after removing direct mode. |
| `README.md` | Direct-mode instructions and examples references | Update to reflect the new architecture. |

---

## 4. Production Hardening

### 4.1 Secrets management

- `core/config.py` already uses `pydantic-settings` with `.env` support. Good.
- For deployment, ensure `Settings` can read from environment variables directly
  (it already does). Document that `.env` is local-only and should not be committed.
- Add a `.env.example` file if one doesn't already exist, listing all required
  variables with placeholder values.

### 4.2 Connection resiliency

- `db/neon.py` should implement retry with exponential backoff for transient
  HTTP errors (429, 502, 503, 504). Use `httpx` with `tenacity` or a simple
  retry loop.
- `db/repository.py` (Postgres store) should handle connection pool exhaustion
  gracefully and log warnings.

### 4.3 Input validation and SQL safety

- `db/neon.py` `run_sql()` must use parameterised queries where possible.
- For arbitrary SQL execution, add guardrails:
  - The safety reviewer (`core/safety.py`) already catches destructive keywords
    at the orchestrator level.
  - In `db/neon.py`, optionally add a read-only mode flag that rejects
    INSERT/UPDATE/DELETE at the transport layer.

### 4.4 Health checks

- `core/orchestrator.py` `/health` and `/ready` are already present.
- The `/ready` endpoint should additionally verify the database connection
  (ping the pool) when `store_backend == "postgres"`.
- The `/ready` endpoint should verify Neon Data API connectivity when the
  Database Agent is configured.

### 4.5 Graceful shutdown

- `run_system.py` already handles SIGINT/SIGTERM. Good.
- Ensure the Postgres connection pool (if used) is closed during shutdown via
  the FastAPI lifespan context manager.

### 4.6 Rate limiting

- Already implemented with `slowapi`. Default is `30/minute`. Confirm this is
  suitable for production or make it configurable (it already reads from
  `settings.rate_limit`).

### 4.7 CORS

- Currently defaults to `allowed_origins = "*"`. For production, this **must** be
  set to explicit origins. The config already supports comma-separated origins.
  Document this clearly.

---

## 5. Test Updates

### 5.1 New tests to write

| Test file | Coverage |
|---|---|
| `tests/unit/test_neon.py` | Unit tests for `db/neon.py` — mock httpx calls, verify SQL generation, error handling. |
| `tests/unit/test_database_agent.py` | Unit tests for `agents/database_agent.py` — verify tool registration, factory output. |
| `tests/unit/test_repository_async.py` | Unit tests for the async `PostgresConversationStore` if refactored. |

### 5.2 Existing tests to update

| Test file | What changes |
|---|---|
| `tests/conftest.py` | Remove `DATABASE_MODE=direct` default. Update mock agent setup since Database Agent is now custom, not MCP. |
| `tests/test_orchestrator.py` | Remove any direct-mode tests. Update mocks to match new Database Agent type. |
| `tests/unit/test_mcp.py` | Keep as-is (MCP is still a generic feature). Remove any Neon-specific assertions if present. |
| `tests/unit/test_agents_config.py` | Update sample configs to reflect Database Agent as `type: custom`. |

### 5.3 Delete example-related tests (if any exist)

The `examples/` directory had no tests, so no test deletions needed.

---

## 6. Documentation Updates

### 6.1 Files to update

| File | Changes |
|---|---|
| `README.md` | Remove direct-mode instructions. Remove examples directory references. Add Neon Data API config instructions. Update Quick Start with new env vars (`NEON_DATABASE_URL`). |
| `EXTENDING.md` | Update the MCP agent example to use a non-Neon MCP server. Add a section showing how the Database Agent works as a custom agent with `@tool` functions. |
| `agents.yaml` | Already covered in section 1.3. |
| `docs/architecture.md` | Update diagrams to show Database Agent as a custom agent calling Neon Data API instead of MCP. |
| `docs/demo-brd-use-case.md` | No major changes needed; the flow is the same. Update setup instructions if env vars changed. |

### 6.2 Files to delete

| File | Reason |
|---|---|
| `docs/presentation/a2a-framework-presentation.md` | Not runtime documentation. |
| `docs/presentation/generate_presentation.py` | Not runtime code. |

After deleting both files, remove the `docs/presentation/` directory.

---

## 7. Dependency Changes (`pyproject.toml`)

### Add
- `psycopg[binary,pool]>=3.1.0` (or `asyncpg>=0.29.0` — pick one)
- `tenacity>=8.0.0` (for retry logic in `db/neon.py`; optional if hand-rolled)

### Remove
- `psycopg2-binary>=2.9.0`

### Keep
- All current deps including `httpx` (used by both MCP client and new Neon Data API client)
- `strands-agents[a2a,gemini]`, `a2a-sdk`, `fastapi`, `uvicorn`, `pydantic-settings`, etc.

### Dev deps — keep as-is
- `types-psycopg2` → replace with type stubs for the new driver if available

---

## 8. Execution Order

Implement in this order to avoid breaking the working system:

1. **Add `db/neon.py`** — new file, no existing code affected.
2. **Add `agents/database_agent.py`** — new file, no existing code affected.
3. **Update `core/config.py`** — add Neon Data API settings.
4. **Update `agents.yaml`** — switch Database Agent to `type: custom`.
5. **Update `pyproject.toml`** — swap database driver dependency.
6. **Refactor `db/repository.py`** — async + connection pooling.
7. **Update `core/store.py`** — async protocol + async `InMemoryConversationStore`.
8. **Update `core/orchestrator.py`** — await store calls, remove direct mode.
9. **Update `run_system.py`** — remove direct-mode branch.
10. **Delete `examples/` directory**.
11. **Delete `docs/presentation/` directory**.
12. **Update tests** — conftest, orchestrator tests, add new unit tests.
13. **Update documentation** — README, EXTENDING, architecture.
14. **Run full test suite and lint** — `pytest`, `ruff check .`, `mypy`.

---

## 9. Summary of File Operations

### New files
- `db/neon.py`
- `agents/database_agent.py`
- `tests/unit/test_neon.py`
- `tests/unit/test_database_agent.py`

### Modified files
- `core/config.py`
- `core/store.py`
- `core/orchestrator.py`
- `core/server.py` (minor — no Neon-specific changes, just ensure custom agent path works)
- `db/repository.py`
- `agents.yaml`
- `pyproject.toml`
- `run_system.py`
- `README.md`
- `EXTENDING.md`
- `docs/architecture.md`
- `docs/demo-brd-use-case.md`
- `tests/conftest.py`
- `tests/test_orchestrator.py`
- `tests/unit/test_agents_config.py`

### Deleted files
- `examples/mcp_agent.py`
- `examples/a2a_graph.py`
- `examples/a2a_swarm.py`
- `examples/pipeline_agent.py`
- `docs/presentation/a2a-framework-presentation.md`
- `docs/presentation/generate_presentation.py`

### Deleted directories
- `examples/`
- `docs/presentation/`

---

## 10. Performance Monitoring: MCP → Data API Comparison

### 10.1 Add server-side request timing middleware

Create `core/metrics.py` with a FastAPI middleware that records per-request timing:

```python
import time, logging
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"
        logger.info(
            "request_completed",
            extra={"duration_ms": duration_ms, "path": request.url.path, "method": request.method},
        )
        return response
```

Add this middleware to the orchestrator app in `core/orchestrator.py`. The
`X-Response-Time-Ms` header makes timing visible to the frontend and to any
monitoring proxy (Nginx, CloudFront, etc.).

### 10.2 Add a `/metrics` endpoint for Prometheus (optional but recommended)

Use `prometheus-fastapi-instrumentator` or a lightweight custom approach:
- Request count by path and status code
- Request duration histogram (p50, p95, p99)
- Active connections gauge

For deployment behind a reverse proxy, this endpoint should be excluded from
public routing.

### 10.3 Instrument `db/neon.py` with timing

Every call to the Neon Data API should log:
- Operation name (`get_database_tables`, `describe_table_schema`, `run_sql`)
- Duration in milliseconds
- HTTP status code from Neon
- Whether a retry occurred

Use the structured JSON logger already in `core/logging.py` so these appear
in the same log stream.

### 10.4 Instrument the MCP client for comparison

Add timing to `ReconnectingMCPClient.call_tool_async()` in `core/mcp.py`:
- Log tool name, duration, and whether a reconnect happened.
- This lets you compare MCP tool-call latency against Data API latency
  side-by-side in the same log format.

### 10.5 Benchmarking script

Create `scripts/benchmark.py` that:
1. Sends N identical requests to the orchestrator (e.g., "list all tables").
2. Records wall-clock time for each.
3. Outputs a summary: min, max, mean, p50, p95, p99.
4. Accepts a `--mode` flag (`mcp` or `api`) to tag the run.

This gives a before/after comparison dataset.

### 10.6 Deployment monitoring

For production, emit metrics to your observability stack:
- **Option A**: OpenTelemetry (already scaffolded in `core/tracing.py`) — add
  span attributes for `db.system`, `db.operation`, and `db.duration_ms`.
- **Option B**: Structured JSON logs → CloudWatch / Datadog log aggregation.
- Set up a dashboard with: agent response time by agent name, database query
  latency, error rate, and request throughput.

---

## 11. Frontend: Streaming Responses

### 11.1 Add a streaming endpoint to the orchestrator

Create `POST /conversations/{id}/messages/stream` that returns an SSE stream:

```
event: token
data: {"text": "The"}

event: token
data: {"text": " database"}

event: token
data: {"text": " contains"}

event: done
data: {"conversation": { ... full conversation object ... }}
```

Implementation in `core/orchestrator.py`:
- Accept the same `MessageRequest` body.
- Run the agent in a background thread (same as `_invoke_agent`).
- Use a Strands `callback_handler` that pushes tokens to an `asyncio.Queue`.
- The SSE generator reads from the queue and yields `event: token` lines.
- On completion, yield `event: done` with the final conversation state.
- On error, yield `event: error` with a message.

The non-streaming `POST /conversations/{id}/messages` stays as-is for
backward compatibility and API clients.

### 11.2 Create a streaming callback handler

In `core/stream.py`:

```python
import asyncio
from strands.handlers.callback_handler import CallbackHandler

class StreamingCallbackHandler(CallbackHandler):
    def __init__(self, queue: asyncio.Queue):
        self._queue = queue

    def on_llm_new_token(self, token: str, **kwargs) -> None:
        self._queue.put_nowait({"event": "token", "text": token})

    def on_llm_end(self, response, **kwargs) -> None:
        self._queue.put_nowait({"event": "done"})
```

The exact callback method names depend on the Strands SDK version; verify
against `strands.handlers.callback_handler.CallbackHandler` API.

### 11.3 Update the frontend to consume streaming

Replace the current `api.sendMessage()` call with an SSE-based flow:

```javascript
async sendMessageStream(id, content, onToken, onDone, onError) {
  const res = await fetch(`/conversations/${encodeURIComponent(id)}/messages/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // parse SSE frames from buffer...
  }
}
```

In the UI:
- Immediately show a "thinking" indicator (typing dots) when the request starts.
- As `token` events arrive, append text to a live agent message bubble.
- On `done`, replace the live bubble with the final rendered message.
- On `error`, show a toast and stop the stream.

### 11.4 Graceful fallback

If the streaming endpoint fails or the browser doesn't support `ReadableStream`,
fall back to the existing non-streaming `POST /conversations/{id}/messages`.

---

## 12. Frontend: Average Response Time Display

### 12.1 Capture timing on every request

In `ApiClient._request()`, wrap each fetch with `performance.now()`:

```javascript
async _request(path, options = {}) {
  const start = performance.now();
  const res = await fetch(...);
  const durationMs = performance.now() - start;
  this._recordTiming(path, durationMs);
  // ... existing logic
}
```

Also read the `X-Response-Time-Ms` header from the response to capture
server-side time separately.

### 12.2 Track and display average response time

Maintain a rolling window of the last 20 request timings:

```javascript
_timings = [];
_recordTiming(path, ms) {
  this._timings.push({ path, ms, at: Date.now() });
  if (this._timings.length > 20) this._timings.shift();
}
getAverageMs() {
  if (!this._timings.length) return 0;
  return this._timings.reduce((sum, t) => sum + t.ms, 0) / this._timings.length;
}
```

### 12.3 Show in the UI

Add a subtle status bar element (e.g., in the input bar area or the log panel
header) that shows:
- `Avg response: 1.2s` — updated after each request completes.
- For streaming requests, show time-to-first-token and total time separately.

Add to `index.html`:
```html
<span class="response-time" id="response-time"></span>
```

Style it as a muted label in the input bar.

---

## 13. Frontend Bug Fixes and Production Improvements

### 13.1 Bugs to fix

| # | Issue | Fix |
|---|---|---|
| 1 | **`pollTimer`/`startPoll()`/`stopPoll()` are dead code** — declared but never called. Conversations don't auto-refresh if another tab makes changes. | Either call `startPoll()` after `selectConversation()` and `stopPoll()` on deselect, or remove the dead code entirely. With streaming (section 11), polling becomes unnecessary for the active conversation. Keep it only for the sidebar list. |
| 2 | **Welcome hint chips are not interactive** — styled with `cursor: default`, no click handlers. They look like clickable suggestions but do nothing. | Add click handlers that populate `messageInput.value` with the hint text, auto-create a conversation if none selected, and focus the input. Change CSS to `cursor: pointer`. |
| 3 | **Activity log expand/collapse animation broken** — `.activity-body` uses `max-height: 0` for collapse but no `max-height` value for the expanded state, so the CSS transition has no target. | Set `max-height: 500px` (or a reasonable upper bound) on `.activity-body` when not `.collapsed`, or switch to a JS-driven `height` animation. |
| 4 | **SSE reconnect has no backoff** — `connectLogStream` retries every 3s forever with no exponential backoff, flooding the server if it's down. | Implement exponential backoff: 1s, 2s, 4s, 8s, max 30s. Reset on successful connection. |
| 5 | **No typing/thinking indicator** — user sees only a spinner on the send button. The chat area looks frozen during long agent responses. | Show a "thinking" bubble in the chat thread (three animated dots) immediately after sending. Remove it when the response arrives. |
| 6 | **`escapeHtml` creates a new DOM element on every call** — inefficient for large conversations. | Replace with a static element cached once, or use a regex-based approach: `str.replace(/[&<>"']/g, m => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[m])`. |
| 7 | **Network error handling is incomplete** — `fetch()` rejects on network failure but `_request` only catches JSON parse errors. A network timeout or offline state throws an unhandled promise rejection. | Wrap the entire `_request` in try/catch. On `TypeError` (network error), show a user-friendly "Network error — check your connection" toast instead of an opaque error. |
| 8 | **Send button innerHTML restoration is fragile** — the `finally` block in the submit handler rebuilds the SVG from a string literal. If the SVG changes in the future, this breaks silently. | Store the original innerHTML before replacing it, then restore from the stored value. |
| 9 | **No keyboard accessibility on conversation list items** — items are `<div>` with click handlers, not focusable or operable via keyboard. | Add `role="button"` and `tabindex="0"` to `.conv-item` elements. Add `keydown` listener for Enter/Space. |
| 10 | **Toast close race condition** — the 6s `setTimeout` and the manual close button don't coordinate. If the element is already removed, the timeout callback tries to remove it again (harmless but sloppy). | Check `el.parentNode` before removing, or use `el.remove()` which is safe to call on detached elements (it is — this is actually fine in modern browsers). Alternatively, clear the timeout on manual close. |

### 13.2 Production frontend improvements

| # | Improvement | Details |
|---|---|---|
| 1 | **Content Security Policy** | The HTML loads inline scripts via `<script src="/static/app.js">` which is fine, but add a `<meta>` CSP tag or set CSP headers from the server to prevent XSS. The `escapeHtml` function is the only XSS defense currently. |
| 2 | **Cache busting for static assets** | `/static/app.js` and `/static/style.css` have no version hash. Deploying a new version may serve stale cached files. Add a build step that appends a hash, or use `Cache-Control: no-cache` during early deployment. |
| 3 | **Favicon and meta tags** | No favicon, no `<meta name="description">`, no Open Graph tags. Add a favicon and basic meta tags. |
| 4 | **Loading state for initial page load** | On first load, `fetchConversations()` fires but there's no loading indicator for the sidebar. If the API is slow, the sidebar appears empty. Add a skeleton or spinner. |
| 5 | **Mobile: confirm/cancel buttons may overflow** | The BRD card action buttons and approval buttons don't have `flex-wrap: wrap`, so on narrow screens they may overflow. Add `flex-wrap: wrap` to `.brd-card-actions` and `.approval-actions`. |
| 6 | **Textarea auto-resize** | The textarea is fixed at 2 rows. For longer messages it requires scrolling. Add auto-resize up to a max of ~6 rows based on content. |

---

## 14. Updated Execution Order

Revised to include sections 10–13. Implement in this order:

1. **Add `db/neon.py`** — new file, no existing code affected.
2. **Add `agents/database_agent.py`** — new file, no existing code affected.
3. **Update `core/config.py`** — add Neon Data API settings.
4. **Update `agents.yaml`** — switch Database Agent to `type: custom`.
5. **Update `pyproject.toml`** — swap database driver dependency.
6. **Refactor `db/repository.py`** — async + connection pooling.
7. **Update `core/store.py`** — async protocol + async `InMemoryConversationStore`.
8. **Update `core/orchestrator.py`** — await store calls, remove direct mode.
9. **Update `run_system.py`** — remove direct-mode branch.
10. **Add `core/metrics.py`** — timing middleware + instrument `db/neon.py` and `core/mcp.py`.
11. **Add `core/stream.py`** — streaming callback handler.
12. **Add streaming endpoint** to `core/orchestrator.py` (`POST .../messages/stream`).
13. **Fix frontend bugs** (section 13.1, items 1–10).
14. **Add frontend streaming** — SSE consumer, typing indicator, live token rendering.
15. **Add frontend response time display** — timing capture, rolling average, UI element.
16. **Frontend production improvements** (section 13.2).
17. **Delete `examples/` directory**.
18. **Delete `docs/presentation/` directory**.
19. **Add `scripts/benchmark.py`** — MCP vs API comparison script.
20. **Update tests** — conftest, orchestrator tests, add new unit tests.
21. **Update documentation** — README, EXTENDING, architecture.
22. **Run full test suite and lint** — `pytest`, `ruff check .`, `mypy`.

---

## 15. Updated Summary of File Operations

### New files (additions from sections 10–13)
- `core/metrics.py`
- `core/stream.py`
- `scripts/benchmark.py`

### Modified files (additions from sections 10–13)
- `core/orchestrator.py` (streaming endpoint + timing middleware)
- `core/mcp.py` (add timing instrumentation to `call_tool_async`)
- `frontend/app.js` (streaming, timing, bug fixes)
- `frontend/style.css` (thinking indicator, activity animation fix, mobile fixes)
- `frontend/index.html` (response time element, favicon, meta tags)
