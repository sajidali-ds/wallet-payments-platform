import uuid

import asyncpg

from app.db import Executor


async def create_transfer(
    conn: Executor,
    *,
    type: str,
    from_wallet_id: uuid.UUID,
    to_wallet_id: uuid.UUID,
    amount: int,
    initiated_by: uuid.UUID,
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO transfers (type, from_wallet_id, to_wallet_id, amount, initiated_by)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, created_at
        """,
        type,
        from_wallet_id,
        to_wallet_id,
        amount,
        initiated_by,
    )
