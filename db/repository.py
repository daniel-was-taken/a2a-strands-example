"""PostgreSQL-backed query store.

Uses psycopg2 for synchronous access. Connection parameters come from the
DATABASE_URL environment variable (standard ``postgres://…`` connection string).

The ``PostgresStore`` class implements the same ``QueryStore`` protocol as
``InMemoryStore``, making it a drop-in replacement.
"""

from __future__ import annotations

import json
import os

import psycopg2
import psycopg2.extras

from schemas import ActivityEvent, Message, QueryResponse, RequestStatus

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS queries (
    request_id   TEXT PRIMARY KEY,
    approval_id  TEXT UNIQUE,
    status       TEXT NOT NULL,
    query        TEXT NOT NULL DEFAULT '',
    result       TEXT,
    review_verdict TEXT,
    messages     JSONB NOT NULL DEFAULT '[]'::jsonb,
    events       JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at   TEXT NOT NULL
);
"""


def _get_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL environment variable is required for PostgresStore")
    return psycopg2.connect(url)


def _row_to_response(row: dict) -> QueryResponse:
    messages = [Message(**m) for m in (row.get("messages") or [])]
    events = [ActivityEvent(**e) for e in (row["events"] or [])]
    return QueryResponse(
        request_id=row["request_id"],
        approval_id=row.get("approval_id"),
        status=RequestStatus(row["status"]),
        query=row["query"],
        result=row.get("result"),
        review_verdict=row.get("review_verdict"),
        messages=messages,
        events=events,
        created_at=row["created_at"],
    )


class PostgresStore:
    """PostgreSQL implementation of :class:`store.QueryStore`."""

    def __init__(self) -> None:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_CREATE_TABLE)
            conn.commit()

    def save(self, record: QueryResponse) -> None:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO queries
                       (request_id, approval_id, status, query, result, review_verdict, messages, events, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (request_id) DO UPDATE SET
                         approval_id = EXCLUDED.approval_id,
                         status = EXCLUDED.status,
                         query = EXCLUDED.query,
                         result = EXCLUDED.result,
                         review_verdict = EXCLUDED.review_verdict,
                         messages = EXCLUDED.messages,
                         events = EXCLUDED.events,
                         created_at = EXCLUDED.created_at""",
                    (
                        record.request_id,
                        record.approval_id,
                        record.status.value,
                        record.query,
                        record.result,
                        record.review_verdict,
                        json.dumps([m.model_dump() for m in record.messages]),
                        json.dumps([e.model_dump() for e in record.events]),
                        record.created_at,
                    ),
                )
            conn.commit()

    def get(self, request_id: str) -> QueryResponse | None:
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM queries WHERE request_id = %s", (request_id,))
                row = cur.fetchone()
        return _row_to_response(row) if row else None

    def get_by_approval_id(self, approval_id: str) -> QueryResponse | None:
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM queries WHERE approval_id = %s", (approval_id,))
                row = cur.fetchone()
        return _row_to_response(row) if row else None

    def list_all(self) -> list[QueryResponse]:
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM queries ORDER BY created_at DESC")
                rows = cur.fetchall()
        return [_row_to_response(r) for r in rows]

    def add_event(self, request_id: str, event: ActivityEvent) -> None:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE queries
                       SET events = events || %s::jsonb
                       WHERE request_id = %s""",
                    (json.dumps([event.model_dump()]), request_id),
                )
            conn.commit()

    def add_message(self, request_id: str, message: Message) -> None:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE queries
                       SET messages = messages || %s::jsonb
                       WHERE request_id = %s""",
                    (json.dumps([message.model_dump()]), request_id),
                )
            conn.commit()

    def update_status(
        self,
        request_id: str,
        status: RequestStatus,
        result: str | None = None,
        review_verdict: str | None = None,
        approval_id: str | None = None,
    ) -> QueryResponse | None:
        sets = ["status = %s"]
        params: list = [status.value]
        if result is not None:
            sets.append("result = %s")
            params.append(result)
        if review_verdict is not None:
            sets.append("review_verdict = %s")
            params.append(review_verdict)
        if approval_id is not None:
            sets.append("approval_id = %s")
            params.append(approval_id)
        params.append(request_id)

        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    f"UPDATE queries SET {', '.join(sets)} WHERE request_id = %s RETURNING *",
                    params,
                )
                row = cur.fetchone()
            conn.commit()
        return _row_to_response(row) if row else None
