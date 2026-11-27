import uuid

import asyncpg

from app.db import Executor


async def claim(conn: Executor, user_id: uuid.UUID, key: str, request_hash: str) -> bool:
    """Tries to insert the key. True = we own it now; False = it already exists.

    ON CONFLICT DO NOTHING has one property we rely on: if another transaction has inserted the
    same (user_id, key) but not committed yet, this statement WAITS until that transaction ends.
    If it commits we get "conflict" (False); if it rolls back we get to insert (True).
    """
    inserted = await conn.fetchval(
        """
        INSERT INTO idempotency_keys (user_id, key, request_hash)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id, key) DO NOTHING
        RETURNING 1
        """,
        user_id,
        key,
        request_hash,
    )
    return inserted is not None


async def get(conn: Executor, user_id: uuid.UUID, key: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT request_hash, response_status, response_body::text AS response_body
        FROM idempotency_keys
        WHERE user_id = $1 AND key = $2
        """,
        user_id,
        key,
    )


async def save_response(
    conn: Executor,
    *,
    user_id: uuid.UUID,
    key: str,
    status_code: int,
    body: str,
    transfer_id: uuid.UUID,
) -> None:
    await conn.execute(
        """
        UPDATE idempotency_keys
        SET response_status = $3, response_body = $4::jsonb, transfer_id = $5
        WHERE user_id = $1 AND key = $2
        """,
        user_id,
        key,
        status_code,
        body,
        transfer_id,
    )
