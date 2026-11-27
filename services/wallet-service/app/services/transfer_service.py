import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

import asyncpg
import structlog

from app.cache.balance_cache import BalanceCache
from app.constants import SYSTEM_WALLET_ID
from app.exceptions import (
    CannotTransferToSelf,
    IdempotencyKeyInProgress,
    IdempotencyKeyReused,
    InsufficientFunds,
    WalletNotFound,
)
from app.metrics import IDEMPOTENT_REPLAYS, TRANSFER_AMOUNT, TRANSFERS
from app.repositories import idempotency_repository, wallet_repository
from app.services import fraud_service, ledger_service

log = structlog.get_logger()


@dataclass(frozen=True)
class TransferOutcome:
    status_code: int
    body: dict[str, Any]
    replayed: bool  # True when this is a stored response, not a new transfer


def request_hash(to_wallet_id: uuid.UUID, amount: int) -> str:
    """Fingerprint of the request, used to detect "same key, different payload".

    Built from the VALIDATED values with sorted keys, so whitespace or field order in the raw
    JSON cannot change it.
    """
    canonical = json.dumps(
        {"op": "transfer", "to_wallet_id": str(to_wallet_id), "amount": amount},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def create_transfer(
    pool: asyncpg.Pool,
    *,
    user_id: uuid.UUID,
    to_wallet_id: uuid.UUID,
    amount: int,
    idempotency_key: str,
    cache: BalanceCache,
    fraud_policy: fraud_service.FraudPolicy,
) -> TransferOutcome:
    # ---------------------------------------------------------------------------------------
    # CONCURRENCY STRATEGY. Everything below runs in ONE transaction, in this exact order:
    #
    #  1. CLAIM THE IDEMPOTENCY KEY first (INSERT ... ON CONFLICT DO NOTHING).
    #     Two requests with the same key cannot both pass: the second one WAITS on the unique
    #     index until the first commits, then sees the key already exists and replays the stored
    #     response instead of moving money again. This is first on purpose: a waiting duplicate
    #     holds no wallet locks yet, so key waits and wallet waits can never form a cycle.
    #
    #  2. LOCK BOTH WALLETS with SELECT ... FOR UPDATE, ORDER BY id. Always lowest id first,
    #     whatever the direction of the transfer. Deadlock needs a cycle: A->B holds A and waits
    #     for B while B->A holds B and waits for A. With one global order, both transactions
    #     reach the lower wallet first, so one simply waits for the other. No cycle, no deadlock.
    #     We lock the RECEIVER too (not just the sender): otherwise the later UPDATE of the
    #     receiver would acquire locks in "sender, then receiver" order, which is the unsafe
    #     order for half of all pairs.
    #
    #  3. CHECK THE BALANCE only after the locks are held. The balance we read cannot change
    #     until we commit, so "enough money" is still true when we subtract. Checking before
    #     locking would be a classic check-then-act race: 100 parallel requests could all see
    #     enough money and overdraw. (READ COMMITTED is enough here because of the row locks;
    #     SERIALIZABLE would need retry loops for no benefit.)
    #
    #  4. WRITE: transfer row, both balance updates, both ledger entries, the outbox event,
    #     and the stored idempotency response.
    #     COMMIT makes all of it visible at once; any error rolls back all of it, including
    #     the idempotency key. So only SUCCESSFUL transfers are stored: a request that failed
    #     (e.g. insufficient funds) can be retried with the same key.
    #
    #  4b. FRAUD RULE (velocity) runs in the same transaction, right after the write: it counts
    #     this user's recent transfers in Postgres and may record a flag. It never blocks.
    #
    #  5. AFTER COMMIT (never before): invalidate both users' cached balances, then log any
    #     fraud flag. These are best-effort side effects: Postgres already holds the truth, and
    #     nothing in the write path ever READS the balance cache.
    #
    #  6. BACKSTOPS in the database: CHECK (balance >= 0) on user wallets, and the deferred
    #     "ledger entries sum to zero" trigger. If this code ever had a bug, Postgres would
    #     refuse to commit the bad state.
    # ---------------------------------------------------------------------------------------
    sender = await wallet_repository.get_by_user_id(pool, user_id)  # plain read, no lock needed
    if sender is None:
        raise WalletNotFound
    from_wallet_id = sender["id"]
    if to_wallet_id == from_wallet_id:
        raise CannotTransferToSelf
    if to_wallet_id == SYSTEM_WALLET_ID:
        raise WalletNotFound  # the system wallet is not a valid destination
    fingerprint = request_hash(to_wallet_id, amount)

    async with pool.acquire() as conn, conn.transaction():
        # Step 1
        if not await idempotency_repository.claim(conn, user_id, idempotency_key, fingerprint):
            return await _replay(conn, user_id, idempotency_key, fingerprint)

        # Step 2
        locked = await wallet_repository.lock_wallets(conn, [from_wallet_id, to_wallet_id])
        wallets = {row["id"]: row for row in locked}
        if to_wallet_id not in wallets:
            raise WalletNotFound

        # Step 3
        if wallets[from_wallet_id]["balance"] < amount:
            raise InsufficientFunds

        # Step 4
        posted = await ledger_service.post_transfer(
            conn,
            type="transfer",
            from_wallet=wallets[from_wallet_id],
            to_wallet=wallets[to_wallet_id],
            amount=amount,
            initiated_by=user_id,
        )
        flag = await fraud_service.evaluate_transfer(
            conn, fraud_policy, user_id=user_id, transfer_id=posted.transfer_id
        )
        body = {
            "transfer_id": str(posted.transfer_id),
            "from_wallet_id": str(from_wallet_id),
            "to_wallet_id": str(to_wallet_id),
            "amount": amount,
            "balance_after": posted.from_balance_after,
            "created_at": posted.created_at.isoformat(),
        }
        await idempotency_repository.save_response(
            conn,
            user_id=user_id,
            key=idempotency_key,
            status_code=201,
            body=json.dumps(body),
            transfer_id=posted.transfer_id,
        )

    affected_users = [wallets[from_wallet_id]["user_id"], wallets[to_wallet_id]["user_id"]]
    await cache.invalidate(affected_users)
    TRANSFERS.labels(type="transfer").inc()
    TRANSFER_AMOUNT.labels(type="transfer").inc(amount)
    if flag is not None:
        fraud_service.report(flag)

    log.info(
        "transfer_completed",
        transfer_id=body["transfer_id"],
        from_wallet_id=body["from_wallet_id"],
        to_wallet_id=body["to_wallet_id"],
        amount=amount,
        idempotency_key=idempotency_key,
    )
    return TransferOutcome(status_code=201, body=body, replayed=False)


async def _replay(
    conn: asyncpg.Connection, user_id: uuid.UUID, key: str, fingerprint: str
) -> TransferOutcome:
    """The key already exists: return the stored response, or refuse if the request differs."""
    row = await idempotency_repository.get(conn, user_id, key)
    if row is None:
        raise IdempotencyKeyInProgress  # should not happen; safe answer is "try again"
    if row["request_hash"] != fingerprint:
        raise IdempotencyKeyReused
    if row["response_status"] is None:
        raise IdempotencyKeyInProgress
    IDEMPOTENT_REPLAYS.inc()
    log.info("idempotent_replay", idempotency_key=key)
    return TransferOutcome(
        status_code=row["response_status"], body=json.loads(row["response_body"]), replayed=True
    )
