import json
import uuid
from typing import Any

import asyncpg

from app.db import Executor


async def add_event(
    conn: Executor, event_type: str, payload: dict[str, Any], request_id: str | None = None
) -> uuid.UUID:
    """Must be called on the SAME connection/transaction as the change it describes."""
    return await conn.fetchval(
        """
        INSERT INTO outbox_events (event_type, payload, request_id)
        VALUES ($1, $2::jsonb, $3)
        RETURNING id
        """,
        event_type,
        json.dumps(payload),
        request_id,
    )


async def lock_unpublished(conn: Executor, limit: int) -> list[asyncpg.Record]:
    """Claims up to `limit` unsent events for this relay instance.

    FOR UPDATE locks the rows; SKIP LOCKED makes a second relay instance silently skip rows the
    first one holds instead of waiting for it. Several relays can therefore drain the backlog in
    parallel without ever picking the same row, and none of them blocks the others.
    """
    return await conn.fetch(
        """
        SELECT id, event_type, payload::text AS payload, request_id, created_at
        FROM outbox_events
        WHERE published_at IS NULL
        ORDER BY created_at, id
        LIMIT $1
        FOR UPDATE SKIP LOCKED
        """,
        limit,
    )


async def mark_published(conn: Executor, event_ids: list[uuid.UUID]) -> None:
    await conn.execute(
        "UPDATE outbox_events SET published_at = now() WHERE id = ANY($1::uuid[])", event_ids
    )


async def backlog_stats(db: Executor) -> asyncpg.Record:
    """Unpublished events and the age of the oldest one (served by the partial index)."""
    return await db.fetchrow(
        """
        SELECT count(*) AS backlog,
               COALESCE(EXTRACT(EPOCH FROM (now() - min(created_at))), 0)::float8 AS oldest_age
        FROM outbox_events
        WHERE published_at IS NULL
        """,
        timeout=2,
    )
