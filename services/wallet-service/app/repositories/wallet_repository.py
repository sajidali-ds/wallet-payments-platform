import uuid

import asyncpg

from app.db import Executor


async def create_user_wallet(db: Executor, user_id: uuid.UUID) -> asyncpg.Record:
    return await db.fetchrow(
        """
        INSERT INTO wallets (user_id, kind)
        VALUES ($1, 'user')
        RETURNING id, user_id, currency, balance, created_at
        """,
        user_id,
    )


async def get_by_user_id(db: Executor, user_id: uuid.UUID) -> asyncpg.Record | None:
    return await db.fetchrow(
        "SELECT id, user_id, currency, balance, created_at FROM wallets WHERE user_id = $1",
        user_id,
    )


async def lock_wallets(conn: Executor, wallet_ids: list[uuid.UUID]) -> list[asyncpg.Record]:
    """Row-locks the wallets until the surrounding transaction ends.

    ORDER BY id: every transaction locks wallets in the same order, so two transactions that
    need the same two wallets can never wait on each other in a circle (deadlock).
    """
    return await conn.fetch(
        """
        SELECT id, user_id, kind, currency, balance
        FROM wallets
        WHERE id = ANY($1::uuid[])
        ORDER BY id
        FOR UPDATE
        """,
        wallet_ids,
    )


async def apply_delta(conn: Executor, wallet_id: uuid.UUID, delta: int) -> int:
    """Atomically adds `delta` (may be negative) and returns the new balance."""
    return await conn.fetchval(
        "UPDATE wallets SET balance = balance + $2 WHERE id = $1 RETURNING balance",
        wallet_id,
        delta,
    )
