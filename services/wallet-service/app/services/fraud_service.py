import uuid
from dataclasses import dataclass

import asyncpg
import structlog

from app.db import Executor
from app.metrics import FRAUD_FLAGS
from app.repositories import fraud_repository

log = structlog.get_logger()


@dataclass(frozen=True)
class FraudPolicy:
    max_transfers: int  # more than this many transfers in the window gets flagged
    window_seconds: int


@dataclass(frozen=True)
class FraudFlag:
    user_id: uuid.UUID
    transfer_count: int
    window_seconds: int
    transfer_id: uuid.UUID


async def evaluate_transfer(
    conn: Executor, policy: FraudPolicy, *, user_id: uuid.UUID, transfer_id: uuid.UUID
) -> FraudFlag | None:
    """Velocity rule. Runs INSIDE the transfer transaction, right after the transfer is recorded.

    Why the database and not Redis: the count includes the transfer being made and is exact,
    it is committed atomically with the transfer, and it keeps working when Redis is down.
    Why it is race-free: all transfers of one user lock the same sender wallet row, so they run
    one after another; each one sees every earlier transfer of that user already committed.
    It only FLAGS. Blocking is not this rule's job, and a false positive must not stop a payment.
    """
    count = await fraud_repository.count_recent_transfers(conn, user_id, policy.window_seconds)
    if count <= policy.max_transfers:
        return None
    created = await fraud_repository.insert_flag_unless_recent(
        conn,
        user_id=user_id,
        transfer_count=count,
        window_seconds=policy.window_seconds,
        transfer_id=transfer_id,
    )
    if not created:
        return None  # already flagged in this window: do not create (or log) a flag per transfer
    return FraudFlag(user_id, count, policy.window_seconds, transfer_id)


def report(flag: FraudFlag) -> None:
    """Called AFTER the transaction commits, so we never log a flag that was rolled back."""
    FRAUD_FLAGS.inc()
    log.warning(
        "fraud_flagged",
        rule="transfer_velocity",
        user_id=str(flag.user_id),
        transfer_count=flag.transfer_count,
        window_seconds=flag.window_seconds,
        transfer_id=str(flag.transfer_id),
    )


async def list_flags(pool: asyncpg.Pool, limit: int) -> list[asyncpg.Record]:
    return await fraud_repository.list_recent(pool, limit)
