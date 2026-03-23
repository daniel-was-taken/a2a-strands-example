"""Orchestrator Agent -- FastAPI app on port 8000.

Receives user requests via REST and forwards them to the Database Agent
using the A2A protocol. Includes a safety review step for destructive queries.
"""

import logging
import os
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from strands import Agent
from strands_tools.a2a_client import A2AClientToolProvider

from agents.model import create_model
from schemas import (
    ErrorResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    RequestStatus,
)
from tools.safety_reviewer import create_safety_reviewer, review_delete_request

logger = logging.getLogger(__name__)

DATABASE_AGENT_URL = os.environ.get("DATABASE_AGENT_URL", "http://localhost:8001/")
ORCHESTRATOR_PORT = int(os.environ.get("ORCHESTRATOR_PORT", "8000"))

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


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.post("/query", response_model=QueryResponse, status_code=201)
def submit_query(payload: QueryRequest) -> QueryResponse:
    """Accept a user query, optionally run safety review, and forward to the Database Agent."""
    request_id = str(uuid4())
    query = payload.query

    if _needs_safety_review(query):
        safety_reviewer = create_safety_reviewer()
        is_approved, verdict = review_delete_request(safety_reviewer, query)

        if not is_approved:
            return QueryResponse(
                request_id=request_id,
                status=RequestStatus.REJECTED,
                result=f"Blocked by safety review: {verdict}",
                review_verdict=verdict,
            )

    try:
        agent = _create_orchestrator_agent()
        response = str(agent(query))
        return QueryResponse(
            request_id=request_id,
            status=RequestStatus.COMPLETED,
            result=response,
        )
    except Exception:
        logger.exception("Query execution failed for request %s", request_id)
        return QueryResponse(
            request_id=request_id,
            status=RequestStatus.FAILED,
            result="Request failed. Please try again.",
        )


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
