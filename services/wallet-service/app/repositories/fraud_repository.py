import uuid

import asyncpg

from app.db import Executor


async def count_recent_transfers(conn: Executor, user_id: uuid.UUID, window_seconds: int) -> int:
    """Transfers this user initiated in the last `window_seconds` (served by a partial index)."""
    return await conn.fetchval(
        """
        SELECT count(*)
        FROM transfers
        WHERE initiated_by = $1
          AND type = 'transfer'
          AND created_at > now() - ($2::int * interval '1 second')
        """,
        user_id,
        window_seconds,
    )


async def insert_flag_unless_recent(
    conn: Executor,
    *,
    user_id: uuid.UUID,
    transfer_count: int,
    window_seconds: int,
    transfer_id: uuid.UUID,
) -> bool:
    """One flag per user per window: skipped if a flag already exists inside the window."""
    flag_id = await conn.fetchval(
        """
        INSERT INTO fraud_flags
            (user_id, rule, transfer_count, window_seconds, triggering_transfer_id)
        SELECT $1::uuid, 'transfer_velocity', $2::int, $3::int, $4::uuid
        WHERE NOT EXISTS (
            SELECT 1 FROM fraud_flags
            WHERE user_id = $1::uuid
              AND rule = 'transfer_velocity'
              AND created_at > now() - ($3::int * interval '1 second')
        )
        RETURNING id
        """,
        user_id,
        transfer_count,
        window_seconds,
        transfer_id,
    )
    return flag_id is not None


async def list_recent(db: Executor, limit: int) -> list[asyncpg.Record]:
    return await db.fetch(
        """
        SELECT id, user_id, rule, transfer_count, window_seconds, triggering_transfer_id, created_at
        FROM fraud_flags
        ORDER BY created_at DESC, id
        LIMIT $1
        """,
        limit,
    )
