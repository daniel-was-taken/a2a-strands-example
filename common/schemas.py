"""Request/response schemas for the orchestrator API."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    AWAITING_APPROVAL = "awaiting_approval"


class ActivityEvent(BaseModel):
    """Single event in the activity log for a conversation."""

    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    agent: str
    action: str
    detail: str = ""


class Message(BaseModel):
    """Single message in a conversation thread."""

    role: Literal["user", "agent"]
    content: str
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class MessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)


class Conversation(BaseModel):
    id: str
    title: str
    status: ConversationStatus = ConversationStatus.ACTIVE
    approval_id: str | None = None
    review_verdict: str | None = None
    review_recommended_reject: bool = False
    pending_query: str | None = None
    messages: list[Message] = Field(default_factory=list)
    events: list[ActivityEvent] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ConversationSummary(BaseModel):
    id: str
    title: str
    status: ConversationStatus
    created_at: str
    updated_at: str


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str = "ok"


# ---------------------------------------------------------------------------
# Backward-compatible aliases — kept until store/orchestrator migration (Task 2+)
# ---------------------------------------------------------------------------

class RequestStatus(StrEnum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    RECOMMENDED_REJECT = "RECOMMENDED_REJECT"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)


class QueryResponse(BaseModel):
    request_id: str
    approval_id: str | None = None
    status: RequestStatus
    query: str = ""
    result: str | None = None
    review_verdict: str | None = None
    messages: list[Message] = Field(default_factory=list)
    events: list[ActivityEvent] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
