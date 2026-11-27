import uuid

from app.db import Executor


async def mark_processed(conn: Executor, event_id: uuid.UUID, event_type: str) -> bool:
    """True = first time we see this event. False = already handled (a duplicate delivery).

    Same mechanism as the idempotency keys in wallet-service: if a concurrent transaction is
    inserting the same event id, this statement waits for it and then reports a conflict.
    """
    inserted = await conn.fetchval(
        """
        INSERT INTO processed_events (event_id, event_type)
        VALUES ($1, $2)
        ON CONFLICT (event_id) DO NOTHING
        RETURNING 1
        """,
        event_id,
        event_type,
    )
    return inserted is not None
