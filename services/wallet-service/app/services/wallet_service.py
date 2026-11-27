import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import structlog

from app.cache.balance_cache import BalanceCache
from app.constants import SYSTEM_WALLET_ID
from app.exceptions import WalletAlreadyExists, WalletNotFound
from app.metrics import BALANCE_CACHE, TRANSFER_AMOUNT, TRANSFERS
from app.repositories import ledger_repository, wallet_repository
from app.services import ledger_service

log = structlog.get_logger()


@dataclass(frozen=True)
class DepositResult:
    transfer_id: uuid.UUID
    wallet_id: uuid.UUID
    amount: int
    balance_after: int
    created_at: datetime


async def create_wallet(pool: asyncpg.Pool, user_id: uuid.UUID) -> asyncpg.Record:
    try:
        # Same pattern as registration: the UNIQUE (user_id, currency) constraint decides.
        wallet = await wallet_repository.create_user_wallet(pool, user_id)
    except asyncpg.UniqueViolationError:
        raise WalletAlreadyExists from None
    log.info("wallet_created", wallet_id=str(wallet["id"]), user_id=str(user_id))
    return wallet


async def get_wallet_for_user(pool: asyncpg.Pool, user_id: uuid.UUID) -> asyncpg.Record:
    wallet = await wallet_repository.get_by_user_id(pool, user_id)
    if wallet is None:
        raise WalletNotFound
    return wallet


async def get_balance(
    pool: asyncpg.Pool, cache: BalanceCache, user_id: uuid.UUID
) -> dict[str, Any]:
    """Cache-aside read. On a miss (or if Redis is down) the answer comes from Postgres."""
    lookup = await cache.get(user_id)  # the token is the cache generation BEFORE we read Postgres
    if lookup.value is not None:
        BALANCE_CACHE.labels(result="hit").inc()
        return lookup.value
    BALANCE_CACHE.labels(result="miss" if lookup.token is not None else "unavailable").inc()
    wallet = await get_wallet_for_user(pool, user_id)
    value = {
        "wallet_id": str(wallet["id"]),
        "currency": wallet["currency"],
        "balance": wallet["balance"],
    }
    await cache.fill(user_id, lookup.token, value)
    return value


async def list_transactions(
    pool: asyncpg.Pool, user_id: uuid.UUID, *, limit: int, cursor: int | None
) -> tuple[list[asyncpg.Record], int | None]:
    wallet = await get_wallet_for_user(pool, user_id)
    # Ask for one extra row: if it exists there is another page, without a second COUNT query.
    rows = await ledger_repository.list_for_wallet(
        pool, wallet["id"], cursor=cursor, limit=limit + 1
    )
    page = rows[:limit]
    next_cursor = page[-1]["entry_id"] if len(rows) > limit else None
    return page, next_cursor


async def deposit(
    pool: asyncpg.Pool,
    *,
    wallet_id: uuid.UUID,
    amount: int,
    admin_id: uuid.UUID,
    cache: BalanceCache,
) -> DepositResult:
    """Money enters as a transfer FROM the system wallet, so the ledger always balances."""
    if wallet_id == SYSTEM_WALLET_ID:
        raise WalletNotFound

    async with pool.acquire() as conn, conn.transaction():
        # Same locking rule as user transfers: both wallets, always in id order.
        locked = await wallet_repository.lock_wallets(conn, [SYSTEM_WALLET_ID, wallet_id])
        wallets = {row["id"]: row for row in locked}
        if wallet_id not in wallets:
            raise WalletNotFound  # raising inside the transaction block rolls it back
        posted = await ledger_service.post_transfer(
            conn,
            type="deposit",
            from_wallet=wallets[SYSTEM_WALLET_ID],
            to_wallet=wallets[wallet_id],
            amount=amount,
            initiated_by=admin_id,
        )
    # After COMMIT: drop the cached balance. (Best effort: the TTL covers a lost invalidation.)
    await cache.invalidate([wallets[wallet_id]["user_id"]])
    TRANSFERS.labels(type="deposit").inc()
    TRANSFER_AMOUNT.labels(type="deposit").inc(amount)
    log.info(
        "deposit_completed",
        transfer_id=str(posted.transfer_id),
        wallet_id=str(wallet_id),
        amount=amount,
        admin_id=str(admin_id),
    )
    return DepositResult(
        transfer_id=posted.transfer_id,
        wallet_id=wallet_id,
        amount=amount,
        balance_after=posted.to_balance_after,
        created_at=posted.created_at,
    )
