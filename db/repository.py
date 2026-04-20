# db/repository.py
"""PostgreSQL-backed conversation store.

Uses psycopg2 for synchronous access. Connection parameters come from the
DATABASE_URL environment variable (standard ``postgres://...`` connection string).

The ``PostgresConversationStore`` class implements the same ``ConversationStore``
protocol as ``InMemoryConversationStore``, making it a drop-in replacement.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import psycopg2
import psycopg2.extras

from core.config import settings
from core.schemas import ActivityEvent, Conversation, ConversationStatus, Message

_COLUMNS = (
    "id, title, status, approval_id, review_verdict, review_recommended_reject,"
    " pending_query, pending_brd_request, evidence_summary, messages, events,"
    " created_at, updated_at"
)

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS conversations (
    id                         TEXT PRIMARY KEY,
    title                      TEXT NOT NULL DEFAULT '',
    status                     TEXT NOT NULL DEFAULT 'active',
    approval_id                TEXT,
    review_verdict             TEXT,
    review_recommended_reject  BOOLEAN NOT NULL DEFAULT FALSE,
    pending_query              TEXT,
    pending_brd_request        TEXT,
    evidence_summary           TEXT,
    messages                   JSONB NOT NULL DEFAULT '[]'::jsonb,
    events                     JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL
);
"""

_INSERT = f"""\
INSERT INTO conversations ({_COLUMNS})
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def _get_conn():
    if not settings.database_url:
        raise ValueError("DATABASE_URL is required for PostgresConversationStore")
    return psycopg2.connect(settings.database_url)


def _dict_cursor():
    return {"cursor_factory": psycopg2.extras.RealDictCursor}


def _row_to_conversation(row: dict) -> Conversation:
    messages = [Message(**m) for m in (row.get("messages") or [])]
    events = [ActivityEvent(**e) for e in (row.get("events") or [])]
    return Conversation(
        id=row["id"],
        title=row["title"],
        status=ConversationStatus(row["status"]),
        approval_id=row.get("approval_id"),
        review_verdict=row.get("review_verdict"),
        review_recommended_reject=row.get("review_recommended_reject", False),
        pending_query=row.get("pending_query"),
        pending_brd_request=row.get("pending_brd_request"),
        evidence_summary=row.get("evidence_summary"),
        messages=messages,
        events=events,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class PostgresConversationStore:
    """PostgreSQL implementation of :class:`store.ConversationStore`."""

    def __init__(self) -> None:
        with _get_conn() as conn, conn.cursor() as cur:
            cur.execute(_CREATE_TABLE)
            cur.execute(
                "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS pending_brd_request TEXT"
            )
            cur.execute(
                "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS evidence_summary TEXT"
            )
            conn.commit()

    def create(self, conversation: Conversation) -> None:
        with _get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                _INSERT,
                (
                    conversation.id,
                    conversation.title,
                    conversation.status.value,
                    conversation.approval_id,
                    conversation.review_verdict,
                    conversation.review_recommended_reject,
                    conversation.pending_query,
                    conversation.pending_brd_request,
                    conversation.evidence_summary,
                    json.dumps([m.model_dump() for m in conversation.messages]),
                    json.dumps([e.model_dump() for e in conversation.events]),
                    conversation.created_at,
                    conversation.updated_at,
                ),
            )
            conn.commit()

    def get(self, conversation_id: str) -> Conversation | None:
        with _get_conn() as conn, conn.cursor(**_dict_cursor()) as cur:
            cur.execute("SELECT * FROM conversations WHERE id = %s", (conversation_id,))
            row = cur.fetchone()
        return _row_to_conversation(row) if row else None

    def list_all(self) -> list[Conversation]:
        with _get_conn() as conn, conn.cursor(**_dict_cursor()) as cur:
            cur.execute("SELECT * FROM conversations ORDER BY updated_at DESC")
            rows = cur.fetchall()
        return [_row_to_conversation(r) for r in rows]

    def add_message(self, conversation_id: str, message: Message) -> None:
        now = datetime.now(UTC).isoformat()
        with _get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE conversations
                   SET messages = messages || %s::jsonb,
                       updated_at = %s
                   WHERE id = %s""",
                (json.dumps([message.model_dump()]), now, conversation_id),
            )
            conn.commit()

    def add_event(self, conversation_id: str, event: ActivityEvent) -> None:
        with _get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE conversations
                   SET events = events || %s::jsonb
                   WHERE id = %s""",
                (json.dumps([event.model_dump()]), conversation_id),
            )
            conn.commit()

    def update(self, conversation_id: str, **fields: Any) -> Conversation | None:
        if not fields:
            return self.get(conversation_id)

        fields["updated_at"] = datetime.now(UTC).isoformat()

        sets = []
        params: list = []
        for key, value in fields.items():
            if key == "status" and isinstance(value, ConversationStatus):
                value = value.value
            sets.append(f"{key} = %s")
            params.append(value)
        params.append(conversation_id)

        with _get_conn() as conn, conn.cursor(**_dict_cursor()) as cur:
            cur.execute(
                f"UPDATE conversations SET {', '.join(sets)} WHERE id = %s RETURNING *",
                params,
            )
            row = cur.fetchone()
            conn.commit()
        return _row_to_conversation(row) if row else None

    def delete(self, conversation_id: str) -> None:
        with _get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
            conn.commit()
