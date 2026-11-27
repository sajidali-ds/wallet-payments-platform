import json
import uuid
from typing import Any

import asyncpg

from app.db import Executor


async def insert(
    conn: Executor,
    *,
    user_id: uuid.UUID,
    event_id: uuid.UUID,
    type: str,
    message: str,
    payload: dict[str, Any],
) -> None:
    await conn.execute(
        """
        INSERT INTO notifications (user_id, event_id, type, message, payload)
        VALUES ($1, $2, $3, $4, $5::jsonb)
        ON CONFLICT (event_id, user_id) DO NOTHING
        """,
        user_id,
        event_id,
        type,
        message,
        json.dumps(payload),
    )


async def list_for_user(
    db: Executor, user_id: uuid.UUID, *, cursor: int | None, limit: int
) -> list[asyncpg.Record]:
    """Newest first, keyset pagination (same approach as the wallet history)."""
    return await db.fetch(
        """
        SELECT id, event_id, type, message, read_at, created_at
        FROM notifications
        WHERE user_id = $1 AND ($2::bigint IS NULL OR id < $2)
        ORDER BY id DESC
        LIMIT $3
        """,
        user_id,
        cursor,
        limit,
    )
