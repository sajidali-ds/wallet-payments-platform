import uuid

import asyncpg

from app.db import Executor


async def add_entry(
    conn: Executor, *, transfer_id: uuid.UUID, wallet_id: uuid.UUID, amount: int, balance_after: int
) -> None:
    await conn.execute(
        """
        INSERT INTO ledger_entries (transfer_id, wallet_id, amount, balance_after)
        VALUES ($1, $2, $3, $4)
        """,
        transfer_id,
        wallet_id,
        amount,
        balance_after,
    )


async def list_for_wallet(
    db: Executor, wallet_id: uuid.UUID, *, cursor: int | None, limit: int
) -> list[asyncpg.Record]:
    """Newest first. Keyset pagination: "entries with id < cursor", not OFFSET.

    OFFSET gets slower the deeper you page and shifts when new rows arrive; the keyset version
    always uses the (wallet_id, id DESC) index and never skips or repeats a row. Entries of one
    wallet are inserted while holding that wallet's row lock, so their ids grow in commit order,
    which is what makes "id < cursor" safe.
    """
    return await db.fetch(
        """
        SELECT le.id AS entry_id,
               le.transfer_id,
               t.type,
               le.amount,
               le.balance_after,
               other.wallet_id AS counterparty_wallet_id,
               le.created_at
        FROM ledger_entries le
        JOIN transfers t ON t.id = le.transfer_id
        JOIN ledger_entries other
          ON other.transfer_id = le.transfer_id AND other.wallet_id <> le.wallet_id
        WHERE le.wallet_id = $1
          AND ($2::bigint IS NULL OR le.id < $2)
        ORDER BY le.id DESC
        LIMIT $3
        """,
        wallet_id,
        cursor,
        limit,
    )
