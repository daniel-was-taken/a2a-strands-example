"""Orchestrator Agent -- FastAPI app on port 8000.

Receives user requests via REST and routes them to specialist agents
(declared in agents.yaml) via the A2A protocol.  Includes a safety
review step for destructive queries.
"""

import asyncio
import logging
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

from core.config import settings
from core.log_stream import broadcaster
from core.log_stream import install as install_sse_handler
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
from core.store import conversation_store

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
            from core.server import create_mcp_agent, load_agents_config

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


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if _FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_FRONTEND_DIR)), name="static")


def _needs_safety_review(user_input: str) -> bool:
    words = set(user_input.lower().split())
    return bool(words & DESTRUCTIVE_KEYWORDS)


def _clear_approval(conversation_id: str) -> None:
    conversation_store.update(
        conversation_id,
        status=ConversationStatus.ACTIVE,
        approval_id=None,
        review_verdict=None,
        review_recommended_reject=False,
        pending_query=None,
    )


def _clear_brd_workflow(conversation_id: str) -> None:
    conversation_store.update(
        conversation_id,
        status=ConversationStatus.ACTIVE,
        pending_brd_request=None,
        evidence_summary=None,
    )


def _add_event(conversation_id: str, agent: str, action: str, detail: str = "") -> None:
    conversation_store.add_event(
        conversation_id,
        ActivityEvent(agent=agent, action=action, detail=detail),
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
    if settings.database_mode != "a2a":
        return False

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
    _add_event(conversation_id, "orchestrator", "forwarding", forwarding_detail)
    response, routed_agents = await asyncio.to_thread(_invoke_agent, prompt)

    for name in routed_agents:
        _add_event(
            conversation_id,
            name.lower().replace(" ", "_"),
            "executed",
            f"Handled by {name}",
        )

    _add_event(conversation_id, "orchestrator", "completed", completion_detail)
    return response


async def _execute_message(conversation_id: str) -> Conversation:
    """Reset agent context, rebuild from conversation messages, execute, store response."""
    conv = conversation_store.get(conversation_id)
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
        conversation_store.add_message(conversation_id, Message(role="agent", content=response))
        return conversation_store.get(conversation_id)  # type: ignore[return-value]
    except Exception:
        logger.exception("Message execution failed for conversation %s", conversation_id)
        _add_event(conversation_id, "orchestrator", "failed", "Message execution failed")
        conversation_store.add_message(
            conversation_id,
            Message(role="agent", content="Something went wrong. Please try again."),
        )
        return conversation_store.get(conversation_id)  # type: ignore[return-value]


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/ready", response_model=HealthResponse)
def readiness() -> HealthResponse:
    try:
        _get_agent()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
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
def create_conversation() -> Conversation:
    conv = Conversation(id=str(uuid4()), title="New conversation")
    conversation_store.create(conv)
    return conv


@app.get("/conversations", response_model=list[ConversationSummary])
def list_conversations() -> list[ConversationSummary]:
    conversations = conversation_store.list_all()
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
def get_conversation(conversation_id: str) -> Conversation:
    conv = conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@app.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str) -> None:
    conv = conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation_store.delete(conversation_id)


@app.post("/conversations/{conversation_id}/messages", response_model=Conversation)
async def send_message(conversation_id: str, payload: MessageRequest) -> Conversation:
    conv = conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.status == ConversationStatus.AWAITING_APPROVAL:
        raise HTTPException(status_code=409, detail="Conversation is awaiting approval")
    if conv.status == ConversationStatus.AWAITING_BRD_CONFIRMATION:
        raise HTTPException(status_code=409, detail="Conversation is awaiting BRD confirmation")

    content = payload.content
    conversation_store.add_message(conversation_id, Message(role="user", content=content))

    # Update title from first message
    conv = conversation_store.get(conversation_id)  # type: ignore[assignment]
    if conv.title == "New conversation":
        title = content[:50] + ("..." if len(content) > 50 else "")
        conversation_store.update(conversation_id, title=title)

    _add_event(conversation_id, "orchestrator", "received", f"Message received: {content[:120]}")

    if _needs_safety_review(content):
        _add_event(
            conversation_id, "safety_reviewer", "review_started", "Evaluating destructive query"
        )
        safety_reviewer = create_safety_reviewer()
        is_approved, verdict = review_delete_request(safety_reviewer, content)
        _add_event(conversation_id, "safety_reviewer", "review_completed", verdict)

        approval_id = token_hex(4)
        conversation_store.update(
            conversation_id,
            status=ConversationStatus.AWAITING_APPROVAL,
            review_verdict=verdict,
            review_recommended_reject=not is_approved,
            pending_query=content,
            approval_id=approval_id,
        )
        if not is_approved:
            _add_event(
                conversation_id,
                "orchestrator",
                "recommended_reject",
                "Safety reviewer recommends rejection",
            )
        else:
            _add_event(
                conversation_id, "orchestrator", "pending_approval", "Awaiting human confirmation"
            )

        return conversation_store.get(conversation_id)  # type: ignore[return-value]

    if _should_start_brd_workflow(content):
        try:
            evidence_summary = await _run_orchestrator_prompt(
                conversation_id,
                _build_fetch_summary_prompt(content),
                "Fetching records for BRD workflow",
                "Evidence summary ready for review",
            )
            conversation_store.add_message(
                conversation_id,
                Message(role="agent", content=evidence_summary),
            )
            conversation_store.update(
                conversation_id,
                status=ConversationStatus.AWAITING_BRD_CONFIRMATION,
                pending_brd_request=content,
                evidence_summary=evidence_summary,
            )
            _add_event(
                conversation_id,
                "orchestrator",
                "awaiting_confirmation",
                "Waiting for human confirmation before BRD drafting",
            )
            return conversation_store.get(conversation_id)  # type: ignore[return-value]
        except Exception:
            logger.exception("BRD evidence fetch failed for conversation %s", conversation_id)
            _add_event(conversation_id, "orchestrator", "failed", "Evidence fetch failed")
            conversation_store.add_message(
                conversation_id,
                Message(
                    role="agent",
                    content="I couldn't fetch the evidence summary for the BRD workflow. Please try again.",
                ),
            )
            return conversation_store.get(conversation_id)  # type: ignore[return-value]

    return await _execute_message(conversation_id)


@app.post("/conversations/{conversation_id}/confirm-evidence", response_model=Conversation)
async def confirm_evidence(conversation_id: str) -> Conversation:
    conv = conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.status != ConversationStatus.AWAITING_BRD_CONFIRMATION:
        raise HTTPException(status_code=409, detail="Conversation is not awaiting BRD confirmation")
    if not conv.pending_brd_request or not conv.evidence_summary:
        raise HTTPException(status_code=409, detail="Conversation is missing BRD workflow data")

    _add_event(conversation_id, "human", "confirmed_evidence", "Human confirmed evidence summary")

    try:
        brd_response = await _run_orchestrator_prompt(
            conversation_id,
            _build_brd_prompt(conv.pending_brd_request, conv.evidence_summary),
            "Drafting BRD from confirmed evidence",
            "BRD drafted successfully",
        )
        conversation_store.add_message(
            conversation_id,
            Message(role="agent", content=brd_response),
        )
        _clear_brd_workflow(conversation_id)
        return conversation_store.get(conversation_id)  # type: ignore[return-value]
    except Exception:
        logger.exception("BRD drafting failed for conversation %s", conversation_id)
        _add_event(conversation_id, "orchestrator", "failed", "BRD drafting failed")
        conversation_store.add_message(
            conversation_id,
            Message(
                role="agent",
                content="I couldn't create the BRD from the confirmed evidence. Please try again.",
            ),
        )
        _clear_brd_workflow(conversation_id)
        return conversation_store.get(conversation_id)  # type: ignore[return-value]


@app.post("/conversations/{conversation_id}/reject-evidence", response_model=Conversation)
def reject_evidence(conversation_id: str) -> Conversation:
    conv = conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.status != ConversationStatus.AWAITING_BRD_CONFIRMATION:
        raise HTTPException(status_code=409, detail="Conversation is not awaiting BRD confirmation")

    _add_event(
        conversation_id,
        "human",
        "rejected_evidence",
        "Human rejected the fetched evidence summary",
    )
    conversation_store.add_message(
        conversation_id,
        Message(
            role="agent",
            content="BRD generation cancelled. Update the request and try again when you're ready.",
        ),
    )
    _clear_brd_workflow(conversation_id)
    return conversation_store.get(conversation_id)  # type: ignore[return-value]


@app.post("/conversations/{conversation_id}/approve", response_model=Conversation)
async def approve_conversation(conversation_id: str) -> Conversation:
    conv = conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.status != ConversationStatus.AWAITING_APPROVAL:
        raise HTTPException(status_code=409, detail="Conversation is not awaiting approval")

    _add_event(conversation_id, "human", "approved", "Human approved the query")
    _clear_approval(conversation_id)
    return await _execute_message(conversation_id)


@app.post("/conversations/{conversation_id}/reject", response_model=Conversation)
def reject_conversation(conversation_id: str) -> Conversation:
    conv = conversation_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.status != ConversationStatus.AWAITING_APPROVAL:
        raise HTTPException(status_code=409, detail="Conversation is not awaiting approval")

    _add_event(conversation_id, "human", "rejected", "Human rejected the query")
    conversation_store.add_message(
        conversation_id, Message(role="agent", content="Query rejected by user.")
    )
    _clear_approval(conversation_id)
    return conversation_store.get(conversation_id)  # type: ignore[return-value]


@app.get("/", include_in_schema=False)
def serve_frontend():
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
