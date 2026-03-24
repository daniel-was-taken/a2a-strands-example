"""In-memory query store.

Provides a thread-safe store for query records. Implements the ``QueryStore``
protocol so it can be swapped for a persistent backend (Redis, PostgreSQL,
Firestore, etc.) without changing calling code.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Protocol

from schemas import ActivityEvent, Message, QueryResponse, RequestStatus

logger = logging.getLogger(__name__)


class QueryStore(Protocol):
    """Abstract interface for query persistence."""

    def save(self, record: QueryResponse) -> None: ...
    def get(self, request_id: str) -> QueryResponse | None: ...
    def get_by_approval_id(self, approval_id: str) -> QueryResponse | None: ...
    def list_all(self) -> list[QueryResponse]: ...
    def add_event(self, request_id: str, event: ActivityEvent) -> None: ...
    def add_message(self, request_id: str, message: Message) -> None: ...
    def update_status(
        self,
        request_id: str,
        status: RequestStatus,
        result: str | None = None,
        review_verdict: str | None = None,
        approval_id: str | None = None,
    ) -> QueryResponse | None: ...


class InMemoryStore:
    """Thread-safe dict-backed implementation of :class:`QueryStore`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, QueryResponse] = {}

    def save(self, record: QueryResponse) -> None:
        with self._lock:
            self._records[record.request_id] = record

    def get(self, request_id: str) -> QueryResponse | None:
        with self._lock:
            return self._records.get(request_id)

    def get_by_approval_id(self, approval_id: str) -> QueryResponse | None:
        with self._lock:
            for rec in self._records.values():
                if rec.approval_id == approval_id:
                    return rec
            return None

    def list_all(self) -> list[QueryResponse]:
        with self._lock:
            return sorted(
                self._records.values(),
                key=lambda r: r.created_at,
                reverse=True,
            )

    def add_event(self, request_id: str, event: ActivityEvent) -> None:
        with self._lock:
            rec = self._records.get(request_id)
            if rec:
                rec.events.append(event)

    def add_message(self, request_id: str, message: Message) -> None:
        with self._lock:
            rec = self._records.get(request_id)
            if rec:
                rec.messages.append(message)

    def update_status(
        self,
        request_id: str,
        status: RequestStatus,
        result: str | None = None,
        review_verdict: str | None = None,
        approval_id: str | None = None,
    ) -> QueryResponse | None:
        with self._lock:
            rec = self._records.get(request_id)
            if rec:
                rec.status = status
                if result is not None:
                    rec.result = result
                if review_verdict is not None:
                    rec.review_verdict = review_verdict
                if approval_id is not None:
                    rec.approval_id = approval_id
                return rec
            return None


# Singleton used by the application.
def _create_store() -> QueryStore:
    backend = os.environ.get("STORE_BACKEND", "memory")
    if backend == "postgres":
        from db.repository import PostgresStore

        logger.info("Using PostgresStore (DATABASE_URL)")
        return PostgresStore()
    logger.info("Using InMemoryStore")
    return InMemoryStore()


query_store: QueryStore = _create_store()
