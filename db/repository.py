# db/repository.py
"""PostgreSQL-backed conversation store (async, pooled).

Uses ``psycopg`` v3 + ``psycopg_pool.AsyncConnectionPool`` so connection
acquisition is pooled rather than per-operation. Migrations live in
``db/migrations.py`` and are applied once during orchestrator startup via
``PostgresConversationStore.startup()``.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Json
from psycopg_pool import AsyncConnectionPool

from core.config import settings
from core.schemas import ActivityEvent, Conversation, ConversationStatus, Message

logger = logging.getLogger(__name__)

_COLUMNS = (
    "id, title, status, approval_id, review_verdict, review_recommended_reject,"
    " pending_query, pending_brd_request, evidence_summary, messages, events,"
    " created_at, updated_at"
)

_INSERT = f"""\
INSERT INTO conversations ({_COLUMNS})
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


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
    """Async PostgreSQL implementation of :class:`store.ConversationStore`."""

    def __init__(self, pool: AsyncConnectionPool | None = None) -> None:
        if pool is not None:
            self._pool = pool
            self._owns_pool = False
            return

        if not settings.database_url:
            raise ValueError("DATABASE_URL is required for PostgresConversationStore")
        self._pool = AsyncConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=10,
            open=False,
        )
        self._owns_pool = True

    async def startup(self) -> None:
        """Open the pool and run migrations. Call once at app startup."""
        from db.migrations import apply_migrations

        if self._owns_pool:
            await self._pool.open()
        await apply_migrations(self._pool)

    async def shutdown(self) -> None:
        """Close the pool (no-op if externally owned)."""
        if self._owns_pool:
            await self._pool.close()

    async def ping(self) -> None:
        """Verify that the pool can acquire a connection and run a trivial query."""
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("SELECT 1")

    async def create(self, conversation: Conversation) -> None:
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
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
                    Json([m.model_dump() for m in conversation.messages]),
                    Json([e.model_dump() for e in conversation.events]),
                    conversation.created_at,
                    conversation.updated_at,
                ),
            )

    async def get(self, conversation_id: str) -> Conversation | None:
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM conversations WHERE id = %s", (conversation_id,))
            row = await cur.fetchone()
        return _row_to_conversation(row) if row else None

    async def list_all(self) -> list[Conversation]:
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM conversations ORDER BY updated_at DESC")
            rows = await cur.fetchall()
        return [_row_to_conversation(r) for r in rows]

    async def add_message(self, conversation_id: str, message: Message) -> None:
        now = datetime.now(UTC).isoformat()
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """UPDATE conversations
                   SET messages = messages || %s::jsonb,
                       updated_at = %s
                   WHERE id = %s""",
                (json.dumps([message.model_dump()]), now, conversation_id),
            )

    async def add_event(self, conversation_id: str, event: ActivityEvent) -> None:
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """UPDATE conversations
                   SET events = events || %s::jsonb
                   WHERE id = %s""",
                (json.dumps([event.model_dump()]), conversation_id),
            )

    async def update(self, conversation_id: str, **fields: Any) -> Conversation | None:
        if not fields:
            return await self.get(conversation_id)

        fields["updated_at"] = datetime.now(UTC).isoformat()

        sets = []
        params: list = []
        for key, value in fields.items():
            if key == "status" and isinstance(value, ConversationStatus):
                value = value.value
            sets.append(f"{key} = %s")
            params.append(value)
        params.append(conversation_id)

        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"UPDATE conversations SET {', '.join(sets)} WHERE id = %s RETURNING *",
                params,
            )
            row = await cur.fetchone()
        return _row_to_conversation(row) if row else None

    async def delete(self, conversation_id: str) -> None:
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
