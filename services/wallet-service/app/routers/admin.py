from typing import Annotated

from fastapi import APIRouter, Query

from app.dependencies import AdminDep, PoolDep
from app.schemas.fraud import FraudFlagResponse
from app.services import fraud_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/fraud-flags")
async def list_fraud_flags(
    admin: AdminDep, pool: PoolDep, limit: Annotated[int, Query(ge=1, le=100)] = 50
) -> list[FraudFlagResponse]:
    rows = await fraud_service.list_flags(pool, limit)
    return [FraudFlagResponse.model_validate(dict(row)) for row in rows]
