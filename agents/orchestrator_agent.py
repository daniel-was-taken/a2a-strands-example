"""Orchestrator Agent -- FastAPI app on port 8000.

Receives user requests via REST and forwards them to the Database Agent
using the A2A protocol. Includes a safety review step for destructive queries.
"""

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import token_hex
from uuid import uuid4

import uvicorn
import yaml
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
    return {f"http://localhost:{cfg['port']}/": cfg["name"] for cfg in agents_config}


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


# ── Lazy-loaded agent singleton ──────────────────────────────────────

_agent_lock = threading.Lock()
_agent: Agent | None = None


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    install_sse_handler()
    logger.info("Starting Orchestrator (mode=%s)", settings.database_mode)
    yield
    logger.info("Shutting down Orchestrator")


limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])


app = FastAPI(
    title="A2A Database Orchestrator",
    description="Orchestrator agent that communicates with a Database Agent via A2A protocol",
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
    """Reject requests without a valid API key (when API_KEY is configured)."""
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


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static assets (CSS, JS) under /static
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if _FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_FRONTEND_DIR)), name="static")


def _needs_safety_review(user_input: str) -> bool:
    """Return True if the query contains destructive keywords."""
    words = set(user_input.lower().split())
    return bool(words & DESTRUCTIVE_KEYWORDS)


def _add_event(request_id: str, agent: str, action: str, detail: str = "") -> None:
    """Append an activity event to a stored query record."""
    query_store.add_event(
        request_id,
        ActivityEvent(agent=agent, action=action, detail=detail),
    )


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


async def _execute_query(request_id: str, query: str) -> QueryResponse:
    """Forward a query to the appropriate agent and return the updated record."""
    _add_event(request_id, "orchestrator", "forwarding", "Routing query to specialist agent")
    try:
        agent = _get_agent()
        # Agent.__call__ is synchronous — run in thread pool to avoid blocking the event loop.
        result = await asyncio.to_thread(agent, query)
        response = str(result)

        routed = _extract_routed_agents(agent)
        for name in routed:
            _add_event(request_id, name.lower().replace(" ", "_"), "executed", f"Handled by {name}")

        _add_event(request_id, "orchestrator", "completed", "Query executed successfully")
        # Populate the initial conversation messages
        query_store.add_message(request_id, Message(role="user", content=query))
        query_store.add_message(request_id, Message(role="agent", content=response))
        rec = query_store.update_status(request_id, RequestStatus.COMPLETED, result=response)
        return rec  # type: ignore[return-value]
    except Exception:
        logger.exception("Query execution failed for request %s", request_id)
        _add_event(request_id, "orchestrator", "failed", "Query execution failed")
        rec = query_store.update_status(
            request_id, RequestStatus.FAILED, result="Request failed. Please try again."
        )
        return rec  # type: ignore[return-value]


async def _execute_reply(request_id: str, reply: str, record: QueryResponse) -> QueryResponse:
    """Handle a follow-up reply within an existing query thread."""
    _add_event(request_id, "orchestrator", "reply", f"Follow-up: {reply[:120]}")
    query_store.add_message(request_id, Message(role="user", content=reply))
    try:
        agent = _get_agent()
        # Build context from previous messages (capped)
        messages = record.messages[-MAX_THREAD_MESSAGES:]
        context_parts = []
        for msg in messages:
            label = "User" if msg.role == "user" else "Agent"
            context_parts.append(f"{label}: {msg.content}")
        context_parts.append(f"User: {reply}")
        prompt = "Previous conversation:\n" + "\n".join(context_parts)

        # Agent.__call__ is synchronous — run in thread pool to avoid blocking the event loop.
        result = await asyncio.to_thread(agent, prompt)
        response = str(result)
        query_store.add_message(request_id, Message(role="agent", content=response))
        _add_event(request_id, "orchestrator", "reply_completed", "Follow-up answered")
        rec = query_store.update_status(request_id, RequestStatus.COMPLETED, result=response)
        return rec  # type: ignore[return-value]
    except Exception:
        logger.exception("Reply execution failed for request %s", request_id)
        _add_event(request_id, "orchestrator", "failed", "Follow-up execution failed")
        err_msg = "Follow-up failed. Please try again."
        query_store.add_message(request_id, Message(role="agent", content=err_msg))
        rec = query_store.update_status(request_id, RequestStatus.COMPLETED, result=err_msg)
        return rec  # type: ignore[return-value]


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/ready", response_model=HealthResponse)
def readiness() -> HealthResponse:
    """Readiness probe -- confirms the agent can be initialised."""
    try:
        _get_agent()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return HealthResponse()


@app.get("/logs/stream")
async def log_stream():
    """SSE endpoint that streams log messages to connected clients."""

    async def _generate():
        async with broadcaster.subscribe() as queue:
            while True:
                data = await queue.get()
                yield f"data: {data}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


@app.post("/query", response_model=QueryResponse, status_code=201)
async def submit_query(payload: QueryRequest) -> QueryResponse:
    """Accept a user query, optionally run safety review, and forward to the Database Agent."""
    request_id = str(uuid4())
    query = payload.query

    # Create the record in the store immediately
    record = QueryResponse(
        request_id=request_id,
        status=RequestStatus.COMPLETED,
        query=query,
    )
    query_store.save(record)
    _add_event(request_id, "orchestrator", "received", f"Query received: {query[:120]}")

    if _needs_safety_review(query):
        _add_event(request_id, "safety_reviewer", "review_started", "Evaluating destructive query")
        safety_reviewer = create_safety_reviewer()
        is_approved, verdict = review_delete_request(safety_reviewer, query)
        _add_event(request_id, "safety_reviewer", "review_completed", verdict)

        if not is_approved:
            query_store.update_status(
                request_id,
                RequestStatus.RECOMMENDED_REJECT,
                review_verdict=verdict,
            )
            _add_event(
                request_id,
                "orchestrator",
                "recommended_reject",
                "Safety reviewer recommends rejection",
            )
            return query_store.get(request_id)  # type: ignore[return-value]

        # Approved by safety reviewer -> park for human confirmation
        approval_id = token_hex(4)
        query_store.update_status(
            request_id,
            RequestStatus.PENDING_APPROVAL,
            review_verdict=verdict,
            approval_id=approval_id,
        )
        _add_event(request_id, "orchestrator", "pending_approval", "Awaiting human confirmation")
        return query_store.get(request_id)  # type: ignore[return-value]

    # Non-destructive -> execute immediately
    return await _execute_query(request_id, query)


@app.get("/queries", response_model=list[QueryResponse])
def list_queries() -> list[QueryResponse]:
    """Return all stored queries (newest first)."""
    return query_store.list_all()


@app.get("/queries/{request_id}", response_model=QueryResponse)
def get_query(request_id: str) -> QueryResponse:
    """Return a single query by its request_id."""
    record = query_store.get(request_id)
    if not record:
        raise HTTPException(status_code=404, detail="Query not found")
    return record


@app.post("/queries/approve/{approval_id}", response_model=QueryResponse)
async def approve_query(approval_id: str) -> QueryResponse:
    """Human approves a PENDING_APPROVAL query -> execute it."""
    record = query_store.get_by_approval_id(approval_id)
    if not record:
        raise HTTPException(status_code=404, detail="Query not found")
    if record.status != RequestStatus.PENDING_APPROVAL:
        raise HTTPException(status_code=409, detail="Query is not pending approval")
    _add_event(record.request_id, "human", "approved", "Human approved the query")
    return await _execute_query(record.request_id, record.query)


@app.post("/queries/reject/{approval_id}", response_model=QueryResponse)
def reject_query(approval_id: str) -> QueryResponse:
    """Human rejects a PENDING_APPROVAL query."""
    record = query_store.get_by_approval_id(approval_id)
    if not record:
        raise HTTPException(status_code=404, detail="Query not found")
    if record.status != RequestStatus.PENDING_APPROVAL:
        raise HTTPException(status_code=409, detail="Query is not pending approval")
    _add_event(record.request_id, "human", "rejected", "Human rejected the query")
    rec = query_store.update_status(
        record.request_id, RequestStatus.REJECTED, result="Rejected by user."
    )
    return rec  # type: ignore[return-value]


@app.post("/query/{request_id}/reply", response_model=QueryResponse)
async def reply_to_query(request_id: str, payload: QueryRequest) -> QueryResponse:
    """Send a follow-up message to an existing completed query thread."""
    record = query_store.get(request_id)
    if not record:
        raise HTTPException(status_code=404, detail="Query not found")
    if record.status != RequestStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Can only reply to completed queries")
    if len(record.messages) >= MAX_THREAD_MESSAGES:
        raise HTTPException(
            status_code=409, detail="Conversation thread has reached the message limit"
        )
    return await _execute_reply(request_id, payload.query, record)


@app.get("/", include_in_schema=False)
def serve_frontend():
    """Serve the frontend HTML."""
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


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    serve()
