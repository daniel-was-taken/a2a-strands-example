"""Schema migrations for the conversations table.

Applied once at startup against a psycopg AsyncConnectionPool.
"""

from __future__ import annotations

import logging

from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

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

_ADD_COLUMNS = [
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS pending_brd_request TEXT",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS evidence_summary TEXT",
]


async def apply_migrations(pool: AsyncConnectionPool) -> None:
    """Run idempotent DDL against the connection pool."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(_CREATE_TABLE)
        for stmt in _ADD_COLUMNS:
            await cur.execute(stmt)
    logger.info("Database migrations applied")
