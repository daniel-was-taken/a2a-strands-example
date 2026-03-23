"""Request/response schemas for the orchestrator API."""

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


class RequestStatus(StrEnum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    RECOMMENDED_REJECT = "RECOMMENDED_REJECT"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class ActivityEvent(BaseModel):
    """Single event in the activity log for a query."""

    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    agent: str
    action: str
    detail: str = ""


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)


class QueryResponse(BaseModel):
    request_id: str
    status: RequestStatus
    query: str = ""
    result: str | None = None
    review_verdict: str | None = None
    events: list[ActivityEvent] = Field(default_factory=list)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
