from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.dependencies import (
    AdminDep,
    BalanceCacheDep,
    CurrentUserDep,
    PoolDep,
    limit_reads,
)
from app.schemas.wallet import (
    BalanceResponse,
    DepositRequest,
    DepositResponse,
    TransactionItem,
    TransactionPage,
    WalletResponse,
)
from app.services import wallet_service

router = APIRouter(prefix="/wallets", tags=["wallets"])

# User-facing routes use /me: the wallet comes from the JWT, never from a client-supplied id,
# so one user cannot read another user's wallet by guessing ids (no IDOR by construction).


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_wallet(user: CurrentUserDep, pool: PoolDep) -> WalletResponse:
    wallet = await wallet_service.create_wallet(pool, user.id)
    return WalletResponse.model_validate(dict(wallet))


@router.get("/me", dependencies=[Depends(limit_reads)])
async def get_my_wallet(user: CurrentUserDep, pool: PoolDep) -> WalletResponse:
    wallet = await wallet_service.get_wallet_for_user(pool, user.id)
    return WalletResponse.model_validate(dict(wallet))


@router.get("/me/balance", dependencies=[Depends(limit_reads)])
async def get_my_balance(
    user: CurrentUserDep, pool: PoolDep, cache: BalanceCacheDep
) -> BalanceResponse:
    # Served from Redis when possible; Postgres is the fallback and the source of truth.
    return BalanceResponse.model_validate(await wallet_service.get_balance(pool, cache, user.id))


@router.get("/me/transactions", dependencies=[Depends(limit_reads)])
async def list_my_transactions(
    user: CurrentUserDep,
    pool: PoolDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[int | None, Query(ge=1)] = None,
) -> TransactionPage:
    rows, next_cursor = await wallet_service.list_transactions(
        pool, user.id, limit=limit, cursor=cursor
    )
    return TransactionPage(
        items=[TransactionItem.model_validate(dict(row)) for row in rows],
        next_cursor=next_cursor,
    )


@router.post("/{wallet_id}/deposit", status_code=status.HTTP_201_CREATED)
async def deposit(
    wallet_id: UUID,
    body: DepositRequest,
    admin: AdminDep,
    pool: PoolDep,
    cache: BalanceCacheDep,
) -> DepositResponse:
    result = await wallet_service.deposit(
        pool, wallet_id=wallet_id, amount=body.amount, admin_id=admin.id, cache=cache
    )
    return DepositResponse(
        transfer_id=result.transfer_id,
        wallet_id=result.wallet_id,
        amount=result.amount,
        balance_after=result.balance_after,
        created_at=result.created_at,
    )
