"""Orchestrator Agent -- FastAPI app on port 8000.

Receives user requests via REST and forwards them to the Database Agent
using the A2A protocol. Includes a safety review step for destructive queries.
"""

import logging
import os
from pathlib import Path
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from strands import Agent
from strands_tools.a2a_client import A2AClientToolProvider

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

logger = logging.getLogger(__name__)

DATABASE_AGENT_URL = os.environ.get("DATABASE_AGENT_URL", "http://localhost:8001/")
ORCHESTRATOR_PORT = int(os.environ.get("ORCHESTRATOR_PORT", "8000"))
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")

DESTRUCTIVE_KEYWORDS = {"delete", "remove", "drop", "truncate", "destroy"}

ORCHESTRATOR_SYSTEM_PROMPT = """
You are the Orchestrator Agent. You receive database-related questions from users
and forward them to the Database Agent for execution.

Use the available A2A tools to communicate with the Database Agent.
Keep responses clear and relay the results back accurately.
"""


app = FastAPI(
    title="A2A Database Orchestrator",
    description="Orchestrator agent that communicates with a Database Agent via A2A protocol",
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)

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


def _create_orchestrator_agent() -> Agent:
    """Build the orchestrator agent with A2A client tools."""
    provider = A2AClientToolProvider(known_agent_urls=[DATABASE_AGENT_URL])
    model = create_model()
    return Agent(
        model=model,
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        tools=provider.tools,
    )


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
        agent = _create_orchestrator_agent()
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
            query_store.update_status(request_id, RequestStatus.REJECTED)
            record = query_store.get(request_id)  # type: ignore[assignment]
            record.review_verdict = verdict  # type: ignore[union-attr]
            return record  # type: ignore[return-value]

        # Approved by safety reviewer → park for human confirmation
        query_store.update_status(request_id, RequestStatus.PENDING_APPROVAL)
        record = query_store.get(request_id)  # type: ignore[assignment]
        record.review_verdict = verdict  # type: ignore[union-attr]
        _add_event(request_id, "orchestrator", "pending_approval", "Awaiting human confirmation")
        return record  # type: ignore[return-value]

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


@app.post("/queries/{request_id}/approve", response_model=QueryResponse)
def approve_query(request_id: str) -> QueryResponse:
    """Human approves a PENDING_APPROVAL query → execute it."""
    record = query_store.get(request_id)
    if not record:
        raise HTTPException(status_code=404, detail="Query not found")
    if record.status != RequestStatus.PENDING_APPROVAL:
        raise HTTPException(status_code=409, detail="Query is not pending approval")
    _add_event(request_id, "human", "approved", "Human approved the query")
    return _execute_query(request_id, record.query)


@app.post("/queries/{request_id}/reject", response_model=QueryResponse)
def reject_query(request_id: str) -> QueryResponse:
    """Human rejects a PENDING_APPROVAL query."""
    record = query_store.get(request_id)
    if not record:
        raise HTTPException(status_code=404, detail="Query not found")
    if record.status != RequestStatus.PENDING_APPROVAL:
        raise HTTPException(status_code=409, detail="Query is not pending approval")
    _add_event(request_id, "human", "rejected", "Human rejected the query")
    rec = query_store.update_status(
        request_id, RequestStatus.REJECTED, result="Rejected by user."
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
    )
    logger.info("Starting Orchestrator Agent on port %d", ORCHESTRATOR_PORT)
    logger.info("Database Agent URL: %s", DATABASE_AGENT_URL)
    uvicorn.run(app, host="0.0.0.0", port=ORCHESTRATOR_PORT)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    serve()
