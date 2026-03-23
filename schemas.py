"""Request/response schemas for the orchestrator API."""

from enum import StrEnum

from pydantic import BaseModel, Field


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
    status: RequestStatus
    result: str | None = None
    review_verdict: str | None = None


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
