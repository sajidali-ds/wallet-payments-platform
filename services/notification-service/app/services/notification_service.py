import uuid
from dataclasses import dataclass
from typing import Any

import asyncpg
import structlog

from app.repositories import notification_repository, processed_event_repository
from app.schemas.event import EventEnvelope

log = structlog.get_logger()


@dataclass(frozen=True)
class NewNotification:
    user_id: uuid.UUID
    type: str
    message: str
    payload: dict[str, Any]


def format_money(paise: int, currency: str) -> str:
    """Integer arithmetic only: 123456 -> 'INR 1,234.56'. No floats anywhere near money."""
    return f"{currency} {paise // 100:,}.{paise % 100:02d}"


def build_notifications(event: EventEnvelope) -> list[NewNotification]:
    data = event.data
    amount = format_money(data.amount, data.currency)
    payload = {
        "transfer_id": str(data.transfer_id),
        "amount": data.amount,
        "currency": data.currency,
    }
    if data.type == "deposit":
        message = f"{amount} was deposited into your wallet"
        return [NewNotification(data.to_user_id, "deposit.received", message, payload)]
    notifications = [
        NewNotification(data.to_user_id, "transfer.received", f"You received {amount}", payload)
    ]
    if data.from_user_id is not None:
        notifications.append(
            NewNotification(data.from_user_id, "transfer.sent", f"You sent {amount}", payload)
        )
    return notifications


async def handle_transfer_completed(pool: asyncpg.Pool, event: EventEnvelope) -> bool:
    """Creates the notifications for one event. Returns False if it was a duplicate delivery.

    IDEMPOTENCY: the broker delivers at least once, so the same event can arrive twice (relay
    crash, consumer crash before ack, retries). The "processed" marker and the notifications are
    written in ONE transaction:
      - crash before commit  -> neither exists, the redelivery does the whole job;
      - crash after commit   -> the marker exists, the redelivery is recognised and skipped.
    Two deliveries racing each other are serialised by the PRIMARY KEY on event_id.
    """
    async with pool.acquire() as conn, conn.transaction():
        if not await processed_event_repository.mark_processed(
            conn, event.event_id, event.event_type
        ):
            log.info("duplicate_event_skipped", event_id=str(event.event_id))
            return False
        for note in build_notifications(event):
            await notification_repository.insert(
                conn,
                user_id=note.user_id,
                event_id=event.event_id,
                type=note.type,
                message=note.message,
                payload=note.payload,
            )
    log.info("notifications_created", event_id=str(event.event_id))
    return True


async def list_notifications(
    pool: asyncpg.Pool, user_id: uuid.UUID, *, limit: int, cursor: int | None
) -> tuple[list[asyncpg.Record], int | None]:
    rows = await notification_repository.list_for_user(
        pool, user_id, cursor=cursor, limit=limit + 1
    )
    page = rows[:limit]
    return page, (page[-1]["id"] if len(rows) > limit else None)
