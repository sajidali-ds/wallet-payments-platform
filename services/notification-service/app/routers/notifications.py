from typing import Annotated

from fastapi import APIRouter, Query

from app.dependencies import CurrentUserDep, PoolDep
from app.schemas.notification import NotificationItem, NotificationPage
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_my_notifications(
    user: CurrentUserDep,
    pool: PoolDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[int | None, Query(ge=1)] = None,
) -> NotificationPage:
    rows, next_cursor = await notification_service.list_notifications(
        pool, user.id, limit=limit, cursor=cursor
    )
    return NotificationPage(
        items=[NotificationItem.model_validate(dict(row)) for row in rows],
        next_cursor=next_cursor,
    )
