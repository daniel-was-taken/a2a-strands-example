"""Orchestrator Agent -- FastAPI app on port 8000.

Receives user requests via REST and forwards them to the Database Agent
using the A2A protocol. Includes a safety review step for destructive queries.
"""

import logging
import os
import threading
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

from agents.model import create_model
from schemas import (
    ActivityEvent,
    ErrorResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    RequestStatus,
)
from store import query_store
from tools.safety_reviewer import create_safety_reviewer, review_delete_request

from log_stream import broadcaster, install as install_sse_handler

logger = logging.getLogger(__name__)

DATABASE_MODE = os.environ.get("DATABASE_MODE", "direct")
DATABASE_AGENT_URL = os.environ.get("DATABASE_AGENT_URL", "http://localhost:8001/")
ORCHESTRATOR_PORT = int(os.environ.get("ORCHESTRATOR_PORT", "8000"))
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
API_KEY = os.environ.get("API_KEY", "")
RATE_LIMIT = os.environ.get("RATE_LIMIT", "30/minute")

DESTRUCTIVE_KEYWORDS = {"delete", "remove", "drop", "truncate", "destroy"}

_A2A_SYSTEM_PROMPT = """
You are the Orchestrator Agent. You receive database-related questions from users
and forward them to the Database Agent for execution.

Use the available A2A tools to communicate with the Database Agent.
Keep responses clear and relay the results back accurately.
"""

# ── Lazy-loaded agent singleton ──────────────────────────────────────

_agent_lock = threading.Lock()
_agent: Agent | None = None


def _get_agent() -> Agent:
    """Return the lazily initialised database agent singleton."""
    global _agent
    if _agent is not None:
        return _agent
    with _agent_lock:
        if _agent is not None:
            return _agent
        if DATABASE_MODE == "a2a":
            from strands_tools.a2a_client import A2AClientToolProvider

            provider = A2AClientToolProvider(known_agent_urls=[DATABASE_AGENT_URL])
            _agent = Agent(
                model=create_model(),
                system_prompt=_A2A_SYSTEM_PROMPT,
                tools=provider.tools,
            )
        else:
            from agents.db_agent import create_database_agent

            _agent = create_database_agent()
        return _agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    install_sse_handler()
    logger.info("Starting Orchestrator (mode=%s)", DATABASE_MODE)
    yield
    logger.info("Shutting down Orchestrator")


limiter = Limiter(key_func=get_remote_address, default_limits=[RATE_LIMIT])


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
    if API_KEY and request.url.path not in ("/health", "/ready", "/", "/docs", "/openapi.json"):
        if not request.url.path.startswith("/static"):
            key = request.headers.get("x-api-key", "")
            if key != API_KEY:
                return JSONResponse(
                    status_code=401,
                    content=ErrorResponse(error="unauthorized", detail="Invalid or missing API key").model_dump(),
                )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
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


def _execute_query(request_id: str, query: str) -> QueryResponse:
    """Forward a query to the Database Agent and return the updated record."""
    _add_event(request_id, "orchestrator", "forwarding", "Sending query to Database Agent")
    try:
        agent = _get_agent()
        response = str(agent(query))
        _add_event(request_id, "orchestrator", "completed", "Query executed successfully")
        rec = query_store.update_status(request_id, RequestStatus.COMPLETED, result=response)
        return rec  # type: ignore[return-value]
    except Exception:
        logger.exception("Query execution failed for request %s", request_id)
        _add_event(request_id, "orchestrator", "failed", "Query execution failed")
        rec = query_store.update_status(
            request_id, RequestStatus.FAILED, result="Request failed. Please try again."
        )
        return rec  # type: ignore[return-value]


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/ready", response_model=HealthResponse)
def readiness() -> HealthResponse:
    """Readiness probe — confirms the agent can be initialised."""
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
def submit_query(payload: QueryRequest) -> QueryResponse:
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
                request_id, RequestStatus.RECOMMENDED_REJECT, review_verdict=verdict,
            )
            _add_event(request_id, "orchestrator", "recommended_reject", "Safety reviewer recommends rejection")
            return query_store.get(request_id)  # type: ignore[return-value]

        # Approved by safety reviewer → park for human confirmation
        approval_id = token_hex(4)
        query_store.update_status(
            request_id,
            RequestStatus.PENDING_APPROVAL,
            review_verdict=verdict,
            approval_id=approval_id,
        )
        _add_event(request_id, "orchestrator", "pending_approval", "Awaiting human confirmation")
        return query_store.get(request_id)  # type: ignore[return-value]

    # Non-destructive → execute immediately
    return _execute_query(request_id, query)


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
def approve_query(approval_id: str) -> QueryResponse:
    """Human approves a PENDING_APPROVAL query → execute it."""
    record = query_store.get_by_approval_id(approval_id)
    if not record:
        raise HTTPException(status_code=404, detail="Query not found")
    if record.status != RequestStatus.PENDING_APPROVAL:
        raise HTTPException(status_code=409, detail="Query is not pending approval")
    _add_event(record.request_id, "human", "approved", "Human approved the query")
    return _execute_query(record.request_id, record.query)


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
    logger.info("Starting Orchestrator Agent on port %d (mode=%s)", ORCHESTRATOR_PORT, DATABASE_MODE)
    if DATABASE_MODE == "a2a":
        logger.info("Database Agent URL: %s", DATABASE_AGENT_URL)
    uvicorn.run(app, host="0.0.0.0", port=ORCHESTRATOR_PORT)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    serve()
