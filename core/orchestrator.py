"""Orchestrator Agent -- FastAPI app on port 8000.

Receives user requests via REST and routes them to specialist agents
(declared in agents.yaml) via the A2A protocol.  Includes a safety
review step for destructive queries.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import token_hex
from uuid import uuid4

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

from core.config import settings
from core.log_stream import broadcaster
from core.log_stream import install as install_sse_handler
from core.metrics import TimingMiddleware
from core.model import create_model
from core.safety import create_safety_reviewer, review_delete_request
from core.schemas import (
    ActivityEvent,
    Conversation,
    ConversationStatus,
    ConversationSummary,
    ErrorResponse,
    HealthResponse,
    Message,
    MessageRequest,
)
from core.store import InMemoryConversationStore, conversation_store
from core.stream import AgentStreamAdapter
from core.telemetry import LangfuseMiddleware, LangfuseTracingHook, get_client

logger = logging.getLogger(__name__)

DESTRUCTIVE_KEYWORDS = {"delete", "remove", "drop", "truncate", "destroy"}
FETCH_KEYWORDS = ("fetch", "record", "records", "data", "database", "query")
BRD_KEYWORDS = ("brd", "business requirements document")
DATABASE_AGENT_NAME = "Database Agent"
BRD_SPECIALIST_NAME = "BRD Specialist"
GRAPH_REVIEWER_NAME = "Graph Reviewer"

MAX_THREAD_MESSAGES = 20


def _load_agents_config() -> list[dict]:
    """Load agents list from the YAML config file."""
    from core.server import load_agents_config

    return load_agents_config(settings.agents_config)


def _agent_url(cfg: dict) -> str:
    """Derive the A2A URL for an agent from its config."""
    host = cfg.get("host", "localhost")
    return f"http://{host}:{cfg['port']}/"


def _build_agent_urls(agents_config: list[dict]) -> list[str]:
    return [_agent_url(cfg) for cfg in agents_config]


def _build_agent_names(agents_config: list[dict]) -> dict[str, str]:
    return {_agent_url(cfg): cfg["name"] for cfg in agents_config}


def _build_system_prompt(agents_config: list[dict]) -> str:
    agent_lines = []
    for cfg in agents_config:
        url = _agent_url(cfg)
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


# ── Lazy-loaded agent singleton ──────────────────────────────────────

_agent_lock = threading.Lock()
_agent_execution_lock = threading.Lock()
_agent: Agent | None = None


def _get_agent() -> Agent:
    global _agent
    if _agent is not None:
        return _agent
    with _agent_lock:
        if _agent is not None:
            return _agent
        from strands_tools.a2a_client import A2AClientToolProvider

        agents_config = _load_agents_config()
        known_urls = _build_agent_urls(agents_config)
        provider = A2AClientToolProvider(known_agent_urls=known_urls)
        _agent = Agent(
            model=create_model(),
            system_prompt=_build_system_prompt(agents_config),
            tools=provider.tools,
            callback_handler=None,
            load_tools_from_directory=False,
        )
        _agent.hooks.add_hook(LangfuseTracingHook(agent_name="orchestrator"))
        return _agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    install_sse_handler()
    logger.info("Starting Orchestrator")
    # If the Postgres-backed store is in use, open the pool and apply migrations.
    store = conversation_store
    if hasattr(store, "startup"):
        await store.startup()  # type: ignore[attr-defined]
    try:
        yield
    finally:
        if hasattr(store, "shutdown"):
            await store.shutdown()  # type: ignore[attr-defined]
        from core.telemetry import shutdown as shutdown_telemetry

        shutdown_telemetry()
        logger.info("Shutting down Orchestrator")


limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])


app = FastAPI(
    title="A2A Database Orchestrator",
    description="Orchestrator agent that routes queries to specialist agents via A2A protocol",
    lifespan=lifespan,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content=ErrorResponse(error="rate_limited", detail="Too many requests").model_dump(),
    )


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    exempt_paths = ("/health", "/ready", "/", "/docs", "/openapi.json")
    if (
        settings.api_key
        and request.url.path not in exempt_paths
        and not request.url.path.startswith("/static")
    ):
        key = request.headers.get("x-api-key", "")
        if key != settings.api_key:
            body = ErrorResponse(
                error="unauthorized", detail="Invalid or missing API key"
            ).model_dump()
            return JSONResponse(status_code=401, content=body)
    return await call_next(request)


app.add_middleware(LangfuseMiddleware)
app.add_middleware(TimingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_WEB_EXPORT_DIR = _PROJECT_ROOT / "web" / "out"
_LEGACY_FRONTEND_DIR = _PROJECT_ROOT / "frontend"

# Prefer the Next.js static export (`web/out`) when it has been built; fall
# back to the legacy vanilla frontend for dev/testing without a Node toolchain.
if _WEB_EXPORT_DIR.is_dir():
    _FRONTEND_DIR = _WEB_EXPORT_DIR
elif _LEGACY_FRONTEND_DIR.is_dir():
    _FRONTEND_DIR = _LEGACY_FRONTEND_DIR
else:
    _FRONTEND_DIR = None

if _FRONTEND_DIR is not None:
    # `html=True` makes StaticFiles serve directory index.html automatically,
    # which is required for Next.js's `trailingSlash: true` export layout.
    app.mount("/static", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="static")


def _needs_safety_review(user_input: str) -> bool:
    words = set(user_input.lower().split())
    return bool(words & DESTRUCTIVE_KEYWORDS)


async def _clear_approval(conversation_id: str) -> None:
    await conversation_store.update(
        conversation_id,
        status=ConversationStatus.ACTIVE,
        approval_id=None,
        review_verdict=None,
        review_recommended_reject=False,
        pending_query=None,
    )


async def _clear_brd_workflow(conversation_id: str) -> None:
    await conversation_store.update(
        conversation_id,
        status=ConversationStatus.ACTIVE,
        pending_brd_request=None,
        evidence_summary=None,
    )


async def _add_event(
    conversation_id: str,
    agent: str,
    action: str,
    detail: str = "",
    duration_ms: float | None = None,
    status: str | None = None,
) -> None:
    from core.telemetry import get_trace_url

    await conversation_store.add_event(
        conversation_id,
        ActivityEvent(
            agent=agent,
            action=action,
            detail=detail,
            duration_ms=round(duration_ms, 1) if duration_ms is not None else None,
            status=status,
            trace_url=get_trace_url(),
        ),
    )


def _extract_routed_agents(agent: Agent) -> list[str]:
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


def _get_target_agent_url(agent_name: str) -> str:
    agents_config = _load_agents_config()
    for cfg in agents_config:
        if cfg["name"] == agent_name:
            return _agent_url(cfg)
    raise RuntimeError(f"Agent '{agent_name}' not found in config")


def _should_start_brd_workflow(user_input: str) -> bool:
    lower_input = user_input.lower()
    has_brd_keyword = any(keyword in lower_input for keyword in BRD_KEYWORDS)
    has_fetch_keyword = any(keyword in lower_input for keyword in FETCH_KEYWORDS)
    return has_brd_keyword and has_fetch_keyword


def _build_fetch_summary_prompt(user_request: str) -> str:
    database_agent_url = _get_target_agent_url(DATABASE_AGENT_NAME)
    return f"""You are coordinating the first stage of a fetch-to-BRD workflow.

Use ONLY the Database Agent with this exact target_agent_url:
{database_agent_url}

User request:
{user_request}

Do not write the BRD yet.
Return a structured evidence summary with these exact headings:
1. Data Source
2. Filters Applied
3. Row Count
4. Key Findings
5. Notable Anomalies
6. Missing Data
7. Evidence Summary
"""


def _build_brd_prompt(user_request: str, evidence_summary: str) -> str:
    brd_specialist_url = _get_target_agent_url(BRD_SPECIALIST_NAME)
    graph_reviewer_url = _get_target_agent_url(GRAPH_REVIEWER_NAME)
    return f"""You are coordinating the second stage of a fetch-to-BRD workflow.

First, use ONLY the BRD Specialist with this exact target_agent_url:
{brd_specialist_url}

Then, send the draft to the Graph Reviewer with this exact target_agent_url:
{graph_reviewer_url}

Return only the final revised BRD.

Original user request:
{user_request}

Confirmed evidence summary:
{evidence_summary}

Requirements for the final BRD:
- Audience: mixed audience.
- Separate facts from assumptions.
- Avoid unsupported claims.
- Cite the evidence summary or source-record appendix.
- Highlight missing data explicitly.
- Ask follow-up questions when the evidence is insufficient.

Use these exact section headings:
1. Problem Statement
2. Scope and Exclusions
3. Functional Requirements
4. Assumptions and Constraints
5. Risks and Open Questions
"""


def _invoke_agent(prompt: str) -> tuple[str, list[str]]:
    agent = _get_agent()
    with _agent_execution_lock:
        agent.messages = []
        result = agent(prompt)
        response = str(result)
        routed_agents = _extract_routed_agents(agent)
    return response, routed_agents


async def _run_orchestrator_prompt(
    conversation_id: str,
    prompt: str,
    forwarding_detail: str,
    completion_detail: str,
) -> str:
    from core.telemetry import get_client, set_session

    await _add_event(conversation_id, "orchestrator", "forwarding", forwarding_detail)

    client = get_client()
    span = None
    if client:
        span = client.start_observation(
            name="orchestrator.route",
            as_type="span",
            input={"conversation_id": conversation_id, "prompt_preview": prompt[:200]},
            metadata={"forwarding_detail": forwarding_detail},
        )

    start = time.perf_counter()
    async with set_session(conversation_id):
        response, routed_agents = await asyncio.to_thread(_invoke_agent, prompt)
    duration_ms = (time.perf_counter() - start) * 1000

    if span:
        span.update(output={
            "response_preview": response[:200],
            "routed_agents": routed_agents,
            "duration_ms": round(duration_ms, 1),
        })
        span.end()

    for name in routed_agents:
        await _add_event(
            conversation_id,
            name.lower().replace(" ", "_"),
            "executed",
            f"Handled by {name}",
        )

    await _add_event(
        conversation_id, "orchestrator", "completed", completion_detail,
        duration_ms=duration_ms, status="success",
    )
    return response


async def _execute_message(conversation_id: str) -> Conversation:
    """Reset agent context, rebuild from conversation messages, execute, store response."""
    conv = await conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    try:
        recent = conv.messages[-MAX_THREAD_MESSAGES:]
        if len(recent) <= 1:
            prompt = recent[0].content
        else:
            context_parts = []
            for msg in recent:
                label = "User" if msg.role == "user" else "Agent"
                context_parts.append(f"{label}: {msg.content}")
            prompt = "Previous conversation:\n" + "\n".join(context_parts)

        response = await _run_orchestrator_prompt(
            conversation_id,
            prompt,
            "Routing to specialist agent",
            "Message processed successfully",
        )
        await conversation_store.add_message(
            conversation_id, Message(role="agent", content=response)
        )
        return await conversation_store.get(conversation_id)  # type: ignore[return-value]
    except Exception:
        logger.exception("Message execution failed for conversation %s", conversation_id)
        await _add_event(conversation_id, "orchestrator", "failed", "Message execution failed")
        await conversation_store.add_message(
            conversation_id,
            Message(role="agent", content="Something went wrong. Please try again."),
        )
        return await conversation_store.get(conversation_id)  # type: ignore[return-value]


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/ready", response_model=HealthResponse)
async def readiness() -> HealthResponse:
    try:
        _get_agent()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Verify database connectivity when the Postgres store is in use.
    store = conversation_store
    if not isinstance(store, InMemoryConversationStore) and hasattr(store, "ping"):
        try:
            await store.ping()  # type: ignore[attr-defined]
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"database_unreachable: {exc}") from exc

    # Verify Neon Data API reachability when credentials are configured.
    if settings.neon_database_url and settings.neon_connection_string:
        from db.neon import NeonClient, NeonDataApiError

        try:
            await NeonClient().run_sql("SELECT 1")
        except NeonDataApiError as exc:
            raise HTTPException(status_code=503, detail=f"neon_unreachable: {exc}") from exc

    return HealthResponse()


@app.get("/logs/stream")
async def log_stream():
    async def _generate():
        async with broadcaster.subscribe() as queue:
            while True:
                data = await queue.get()
                yield f"data: {data}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


@app.post("/conversations", response_model=Conversation, status_code=201)
async def create_conversation() -> Conversation:
    conv = Conversation(id=str(uuid4()), title="New conversation")
    await conversation_store.create(conv)
    return conv


@app.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations() -> list[ConversationSummary]:
    conversations = await conversation_store.list_all()
    return [
        ConversationSummary(
            id=c.id,
            title=c.title,
            status=c.status,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in conversations
    ]


@app.get("/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str) -> Conversation:
    conv = await conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@app.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str) -> None:
    conv = await conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await conversation_store.delete(conversation_id)


async def _prepare_user_message(conversation_id: str, content: str) -> Conversation:
    """Store the user message, update title, record an event, and return the conversation."""
    await conversation_store.add_message(conversation_id, Message(role="user", content=content))
    conv = await conversation_store.get(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.title == "New conversation":
        title = content[:50] + ("..." if len(content) > 50 else "")
        await conversation_store.update(conversation_id, title=title)
    await _add_event(
        conversation_id, "orchestrator", "received", f"Message received: {content[:120]}"
    )
    return conv


@app.post("/conversations/{conversation_id}/messages", response_model=Conversation)
async def send_message(conversation_id: str, payload: MessageRequest) -> Conversation:
    conv = await conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.status == ConversationStatus.AWAITING_APPROVAL:
        raise HTTPException(status_code=409, detail="Conversation is awaiting approval")
    if conv.status == ConversationStatus.AWAITING_BRD_CONFIRMATION:
        raise HTTPException(status_code=409, detail="Conversation is awaiting BRD confirmation")

    content = payload.content
    await _prepare_user_message(conversation_id, content)

    # Tag the Langfuse trace with conversation context.
    client = get_client()
    if client:
        try:
            from langfuse._client.propagation import propagate_attributes

            tags = []
            if _needs_safety_review(content):
                tags.append("safety_review")
            elif _should_start_brd_workflow(content):
                tags.append("brd_workflow")
            else:
                tags.append("standard")
            # propagate_attributes is a context manager but we just need
            # to set session_id on the current span/trace.  The middleware
            # already set the root span so this adds metadata.
            propagate_attributes(session_id=conversation_id, tags=tags).__enter__()
        except Exception:
            pass

    if _needs_safety_review(content):
        review_span = None
        if client:
            review_span = client.start_observation(
                name="safety_review",
                as_type="span",
                input={"query": content},
            )

        await _add_event(
            conversation_id, "safety_reviewer", "review_started", "Evaluating destructive query"
        )
        review_start = time.perf_counter()
        safety_reviewer = create_safety_reviewer()
        is_approved, verdict = review_delete_request(safety_reviewer, content)
        review_duration = (time.perf_counter() - review_start) * 1000

        if review_span:
            review_span.update(output={"verdict": verdict, "approved": is_approved})
            review_span.end()

        await _add_event(
            conversation_id, "safety_reviewer", "review_completed", verdict,
            duration_ms=review_duration, status="approved" if is_approved else "rejected",
        )

        approval_id = token_hex(4)
        await conversation_store.update(
            conversation_id,
            status=ConversationStatus.AWAITING_APPROVAL,
            review_verdict=verdict,
            review_recommended_reject=not is_approved,
            pending_query=content,
            approval_id=approval_id,
        )
        if not is_approved:
            await _add_event(
                conversation_id,
                "orchestrator",
                "recommended_reject",
                "Safety reviewer recommends rejection",
            )
        else:
            await _add_event(
                conversation_id, "orchestrator", "pending_approval", "Awaiting human confirmation"
            )

        return await conversation_store.get(conversation_id)  # type: ignore[return-value]

    if _should_start_brd_workflow(content):
        try:
            evidence_summary = await _run_orchestrator_prompt(
                conversation_id,
                _build_fetch_summary_prompt(content),
                "Fetching records for BRD workflow",
                "Evidence summary ready for review",
            )
            await conversation_store.add_message(
                conversation_id,
                Message(role="agent", content=evidence_summary),
            )
            await conversation_store.update(
                conversation_id,
                status=ConversationStatus.AWAITING_BRD_CONFIRMATION,
                pending_brd_request=content,
                evidence_summary=evidence_summary,
            )
            await _add_event(
                conversation_id,
                "orchestrator",
                "awaiting_confirmation",
                "Waiting for human confirmation before BRD drafting",
            )
            return await conversation_store.get(conversation_id)  # type: ignore[return-value]
        except Exception:
            logger.exception("BRD evidence fetch failed for conversation %s", conversation_id)
            await _add_event(conversation_id, "orchestrator", "failed", "Evidence fetch failed")
            await conversation_store.add_message(
                conversation_id,
                Message(
                    role="agent",
                    content="I couldn't fetch the evidence summary for the BRD workflow. "
                    "Please try again.",
                ),
            )
            return await conversation_store.get(conversation_id)  # type: ignore[return-value]

    return await _execute_message(conversation_id)


@app.post("/conversations/{conversation_id}/messages/stream")
async def send_message_stream(conversation_id: str, payload: MessageRequest):
    """SSE streaming variant of send_message.

    Yields ``event: token`` frames as the agent produces tokens, then a final
    ``event: done`` frame with the complete conversation object. Errors emit an
    ``event: error`` frame.
    """
    conv = await conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.status == ConversationStatus.AWAITING_APPROVAL:
        raise HTTPException(status_code=409, detail="Conversation is awaiting approval")
    if conv.status == ConversationStatus.AWAITING_BRD_CONFIRMATION:
        raise HTTPException(status_code=409, detail="Conversation is awaiting BRD confirmation")

    content = payload.content
    await _prepare_user_message(conversation_id, content)

    if _needs_safety_review(content) or _should_start_brd_workflow(content):
        # Workflows that require approval/confirmation aren't streamable tokens;
        # fall back to the non-streaming handler and emit a single "done" frame.
        return StreamingResponse(
            _emit_non_streaming(conversation_id, content),
            media_type="text/event-stream",
        )

    return StreamingResponse(
        _emit_streaming(conversation_id, content),
        media_type="text/event-stream",
    )


async def _emit_non_streaming(conversation_id: str, _content: str):
    try:
        final_conv = await _execute_message(conversation_id)
    except Exception as exc:
        logger.exception("Streaming fallback failed for conversation %s", conversation_id)
        yield _sse("error", {"message": str(exc)})
        return
    yield _sse("done", {"conversation": final_conv.model_dump()})


async def _emit_streaming(conversation_id: str, _content: str):
    """Run the orchestrator agent in a thread and forward tokens as SSE frames."""
    conv = await conversation_store.get(conversation_id)
    if conv is None:
        yield _sse("error", {"message": "Conversation not found"})
        return

    recent = conv.messages[-MAX_THREAD_MESSAGES:]
    if len(recent) <= 1:
        prompt = recent[0].content
    else:
        context_parts = [
            f"{'User' if msg.role == 'user' else 'Agent'}: {msg.content}" for msg in recent
        ]
        prompt = "Previous conversation:\n" + "\n".join(context_parts)

    await _add_event(conversation_id, "orchestrator", "forwarding", "Streaming agent response")

    client = get_client()
    stream_span = None
    if client:
        stream_span = client.start_observation(
            name="stream",
            as_type="span",
            input={"conversation_id": conversation_id},
        )

    adapter = AgentStreamAdapter(_get_agent, _agent_execution_lock)
    buffer: list[str] = []
    stream_start = time.perf_counter()
    ttft_recorded = False

    try:
        async for token in adapter.run(prompt):
            if not ttft_recorded:
                ttft_ms = (time.perf_counter() - stream_start) * 1000
                if stream_span:
                    stream_span.update(metadata={"time_to_first_token_ms": round(ttft_ms, 1)})
                ttft_recorded = True
            buffer.append(token)
            yield _sse("token", {"text": token})

        total_ms = (time.perf_counter() - stream_start) * 1000
        response = "".join(buffer) or adapter.final_text
        routed_agents = adapter.routed_agents(_build_agent_names(_load_agents_config()))

        if stream_span:
            stream_span.update(output={
                "response_preview": response[:200],
                "routed_agents": routed_agents,
                "total_duration_ms": round(total_ms, 1),
            })
            stream_span.end()

        for name in routed_agents:
            await _add_event(
                conversation_id,
                name.lower().replace(" ", "_"),
                "executed",
                f"Handled by {name}",
            )
        await _add_event(
            conversation_id, "orchestrator", "completed", "Message processed successfully",
            duration_ms=total_ms, status="success",
        )
        await conversation_store.add_message(
            conversation_id, Message(role="agent", content=response)
        )
        final_conv = await conversation_store.get(conversation_id)
        yield _sse("done", {"conversation": final_conv.model_dump() if final_conv else None})
    except Exception as exc:
        logger.exception("Streaming failed for conversation %s", conversation_id)
        if stream_span:
            stream_span.update(level="ERROR", status_message=str(exc))
            stream_span.end()
        await _add_event(
            conversation_id, "orchestrator", "failed", "Streaming failed", status="failure",
        )
        await conversation_store.add_message(
            conversation_id,
            Message(role="agent", content="Something went wrong. Please try again."),
        )
        yield _sse("error", {"message": str(exc)})


def _sse(event: str, data: dict) -> str:
    import json as _json

    return f"event: {event}\ndata: {_json.dumps(data, default=str)}\n\n"


@app.post("/conversations/{conversation_id}/confirm-evidence", response_model=Conversation)
async def confirm_evidence(conversation_id: str) -> Conversation:
    conv = await conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.status != ConversationStatus.AWAITING_BRD_CONFIRMATION:
        raise HTTPException(status_code=409, detail="Conversation is not awaiting BRD confirmation")
    if not conv.pending_brd_request or not conv.evidence_summary:
        raise HTTPException(status_code=409, detail="Conversation is missing BRD workflow data")

    await _add_event(
        conversation_id, "human", "confirmed_evidence", "Human confirmed evidence summary"
    )

    client = get_client()
    brd_span = None
    if client:
        brd_span = client.start_observation(
            name="brd.draft",
            as_type="span",
            input={"evidence_preview": (conv.evidence_summary or "")[:200]},
        )

    try:
        brd_response = await _run_orchestrator_prompt(
            conversation_id,
            _build_brd_prompt(conv.pending_brd_request, conv.evidence_summary),
            "Drafting BRD from confirmed evidence",
            "BRD drafted successfully",
        )
        if brd_span:
            brd_span.update(output={"response_preview": brd_response[:200]})
            brd_span.end()
        await conversation_store.add_message(
            conversation_id,
            Message(role="agent", content=brd_response),
        )
        await _clear_brd_workflow(conversation_id)
        return await conversation_store.get(conversation_id)  # type: ignore[return-value]
    except Exception:
        logger.exception("BRD drafting failed for conversation %s", conversation_id)
        if brd_span:
            brd_span.update(level="ERROR", status_message="BRD drafting failed")
            brd_span.end()
        await _add_event(
            conversation_id, "orchestrator", "failed", "BRD drafting failed", status="failure",
        )
        await conversation_store.add_message(
            conversation_id,
            Message(
                role="agent",
                content="I couldn't create the BRD from the confirmed evidence. Please try again.",
            ),
        )
        await _clear_brd_workflow(conversation_id)
        return await conversation_store.get(conversation_id)  # type: ignore[return-value]


@app.post("/conversations/{conversation_id}/reject-evidence", response_model=Conversation)
async def reject_evidence(conversation_id: str) -> Conversation:
    conv = await conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.status != ConversationStatus.AWAITING_BRD_CONFIRMATION:
        raise HTTPException(status_code=409, detail="Conversation is not awaiting BRD confirmation")

    await _add_event(
        conversation_id,
        "human",
        "rejected_evidence",
        "Human rejected the fetched evidence summary",
    )
    await conversation_store.add_message(
        conversation_id,
        Message(
            role="agent",
            content="BRD generation cancelled. Update the request and try again when you're ready.",
        ),
    )
    await _clear_brd_workflow(conversation_id)
    return await conversation_store.get(conversation_id)  # type: ignore[return-value]


@app.post("/conversations/{conversation_id}/approve", response_model=Conversation)
async def approve_conversation(conversation_id: str) -> Conversation:
    conv = await conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.status != ConversationStatus.AWAITING_APPROVAL:
        raise HTTPException(status_code=409, detail="Conversation is not awaiting approval")

    await _add_event(conversation_id, "human", "approved", "Human approved the query")
    await _clear_approval(conversation_id)
    return await _execute_message(conversation_id)


@app.post("/conversations/{conversation_id}/reject", response_model=Conversation)
async def reject_conversation(conversation_id: str) -> Conversation:
    conv = await conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.status != ConversationStatus.AWAITING_APPROVAL:
        raise HTTPException(status_code=409, detail="Conversation is not awaiting approval")

    await _add_event(conversation_id, "human", "rejected", "Human rejected the query")
    await conversation_store.add_message(
        conversation_id, Message(role="agent", content="Query rejected by user.")
    )
    await _clear_approval(conversation_id)
    return await conversation_store.get(conversation_id)  # type: ignore[return-value]


@app.get("/", include_in_schema=False)
def serve_frontend():
    if _FRONTEND_DIR is None:
        return JSONResponse({"detail": "Frontend not found"}, status_code=404)
    index = _FRONTEND_DIR / "index.html"
    if index.is_file():
        return FileResponse(str(index), media_type="text/html")
    return JSONResponse({"detail": "Frontend not found"}, status_code=404)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_server_error",
            detail="An unexpected error occurred.",
        ).model_dump(),
    )


def serve():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logger.info(
        "Starting Orchestrator Agent on port %d",
        settings.orchestrator_port,
    )
    try:
        agents_config = _load_agents_config()
        for cfg in agents_config:
            logger.info("  %s -> http://localhost:%d/", cfg["name"], cfg["port"])
    except Exception:
        logger.warning("Could not load agents config for logging")
    uvicorn.run(app, host="0.0.0.0", port=settings.orchestrator_port)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    serve()
