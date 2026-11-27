"""The ONE place where money moves. Deposits and user transfers both go through post_transfer."""

import uuid
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import structlog

from app.repositories import (
    ledger_repository,
    outbox_repository,
    transfer_repository,
    wallet_repository,
)

TRANSFER_COMPLETED = "transfer.completed"


@dataclass(frozen=True)
class PostedTransfer:
    transfer_id: uuid.UUID
    created_at: datetime
    from_balance_after: int
    to_balance_after: int


async def post_transfer(
    conn: asyncpg.Connection,
    *,
    type: str,
    from_wallet: asyncpg.Record,  # rows returned by lock_wallets: id, user_id, currency, ...
    to_wallet: asyncpg.Record,
    amount: int,
    initiated_by: uuid.UUID,
) -> PostedTransfer:
    """Records a transfer, moves the balances, writes the two ledger entries and the outbox event.

    PRECONDITION: the caller is inside a transaction and already holds FOR UPDATE locks on BOTH
    wallets (wallet_repository.lock_wallets). This function does no locking and no balance check:
    those belong to the caller, who knows the business rules.

    Because the outbox event is written here, next to the ledger entries, EVERY committed
    transfer has exactly one `transfer.completed` event, and a rolled-back one has none.
    """
    transfer = await transfer_repository.create_transfer(
        conn,
        type=type,
        from_wallet_id=from_wallet["id"],
        to_wallet_id=to_wallet["id"],
        amount=amount,
        initiated_by=initiated_by,
    )
    # UPDATE ... RETURNING gives the exact new balance, which becomes the entry's balance_after.
    from_after = await wallet_repository.apply_delta(conn, from_wallet["id"], -amount)
    to_after = await wallet_repository.apply_delta(conn, to_wallet["id"], amount)
    await ledger_repository.add_entry(
        conn,
        transfer_id=transfer["id"],
        wallet_id=from_wallet["id"],
        amount=-amount,
        balance_after=from_after,
    )
    await ledger_repository.add_entry(
        conn,
        transfer_id=transfer["id"],
        wallet_id=to_wallet["id"],
        amount=amount,
        balance_after=to_after,
    )
    # Outbox: the event is just a row in OUR database, committed atomically with the money.
    # Nothing here talks to RabbitMQ, so a broker outage can never fail or lose a transfer.
    from_user_id = from_wallet["user_id"]  # None for the system wallet (deposits)
    # The request id was bound to the logging context by the request-id middleware; storing it on
    # the event lets the consumer's logs be joined with this request's logs.
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    await outbox_repository.add_event(
        conn,
        TRANSFER_COMPLETED,
        {
            "transfer_id": str(transfer["id"]),
            "type": type,
            "from_wallet_id": str(from_wallet["id"]),
            "from_user_id": str(from_user_id) if from_user_id else None,
            "to_wallet_id": str(to_wallet["id"]),
            "to_user_id": str(to_wallet["user_id"]),
            "amount": amount,
            "currency": to_wallet["currency"],
        },
        request_id=request_id,
    )
    return PostedTransfer(
        transfer_id=transfer["id"],
        created_at=transfer["created_at"],
        from_balance_after=from_after,
        to_balance_after=to_after,
    )
