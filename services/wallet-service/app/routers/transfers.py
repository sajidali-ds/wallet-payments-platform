from typing import Annotated

from fastapi import APIRouter, Depends, Header, status
from fastapi.responses import JSONResponse

from app.dependencies import BalanceCacheDep, CurrentUserDep, PoolDep, SettingsDep, limit_transfers
from app.schemas.transfer import TransferRequest, TransferResponse
from app.services import transfer_service
from app.services.fraud_service import FraudPolicy

router = APIRouter(prefix="/transfers", tags=["transfers"])

# Visible ASCII only (UUIDs fit): keeps odd characters out of the database and the logs.
KEY_PATTERN = r"^[A-Za-z0-9._:-]+$"
IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=255, pattern=KEY_PATTERN)
]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=TransferResponse,
    dependencies=[Depends(limit_transfers)],
)
async def create_transfer(
    body: TransferRequest,
    user: CurrentUserDep,
    pool: PoolDep,
    cache: BalanceCacheDep,
    settings: SettingsDep,
    idempotency_key: IdempotencyKey,
) -> JSONResponse:
    outcome = await transfer_service.create_transfer(
        pool,
        user_id=user.id,
        to_wallet_id=body.to_wallet_id,
        amount=body.amount,
        idempotency_key=idempotency_key,
        cache=cache,
        fraud_policy=FraudPolicy(
            max_transfers=settings.fraud_max_transfers_per_window,
            window_seconds=settings.fraud_window_seconds,
        ),
    )
    # A stored response is returned byte-for-byte; the header tells the client it was a replay.
    headers = {"Idempotent-Replay": "true"} if outcome.replayed else None
    return JSONResponse(status_code=outcome.status_code, content=outcome.body, headers=headers)
