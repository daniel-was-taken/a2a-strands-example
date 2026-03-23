"""In-memory query store.

Provides a thread-safe store for query records. Implements the ``QueryStore``
protocol so it can be swapped for a persistent backend (Redis, PostgreSQL,
Firestore, etc.) without changing calling code.
"""

from __future__ import annotations

import threading
from typing import Protocol

from schemas import ActivityEvent, QueryResponse, RequestStatus


class QueryStore(Protocol):
    """Abstract interface for query persistence."""

    def save(self, record: QueryResponse) -> None: ...
    def get(self, request_id: str) -> QueryResponse | None: ...
    def list_all(self) -> list[QueryResponse]: ...
    def add_event(self, request_id: str, event: ActivityEvent) -> None: ...
    def update_status(
        self,
        request_id: str,
        status: RequestStatus,
        result: str | None = None,
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

    def update_status(
        self,
        request_id: str,
        status: RequestStatus,
        result: str | None = None,
    ) -> QueryResponse | None:
        with self._lock:
            rec = self._records.get(request_id)
            if rec:
                rec.status = status
                if result is not None:
                    rec.result = result
                return rec
            return None


# Singleton used by the application.
query_store = InMemoryStore()
