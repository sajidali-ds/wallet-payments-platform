"""Outbox relay: copies unsent outbox rows to the message broker, at least once.

Delivery guarantee: AT LEAST ONCE. If the relay publishes an event and then crashes before
committing "published_at", the event is sent again after restart. That is deliberate (losing an
event is worse) and it is why every consumer must be idempotent (notification-service dedupes on
the event id). Events are NOT strictly ordered across different transfers.
"""

import asyncio
import contextlib
import json
import uuid
from typing import Any, Protocol

import asyncpg
import structlog

from app.metrics import OUTBOX_PUBLISH_FAILURES, OUTBOX_PUBLISHED
from app.repositories import outbox_repository

log = structlog.get_logger()


class Broker(Protocol):
    async def publish(
        self, *, event_id: str, event_type: str, body: bytes, request_id: str | None = None
    ) -> None:
        """Returns only once the broker has confirmed the message; raises if it did not."""


def build_body(row: asyncpg.Record | dict[str, Any]) -> bytes:
    """The message every consumer receives. `event_id` is what they dedupe on."""
    envelope = {
        "event_id": str(row["id"]),
        "event_type": row["event_type"],
        "request_id": row["request_id"],  # correlation id of the request that caused the event
        "occurred_at": row["created_at"].isoformat(),
        "data": json.loads(row["payload"]),
    }
    return json.dumps(envelope).encode("utf-8")


class OutboxRelay:
    def __init__(
        self,
        pool: asyncpg.Pool,
        broker: Broker,
        *,
        batch_size: int = 50,
        poll_interval: float = 1.0,
        max_backoff: float = 30.0,
    ) -> None:
        self._pool = pool
        self._broker = broker
        self._batch_size = batch_size
        self._poll_interval = poll_interval
        self._max_backoff = max_backoff

    async def publish_pending(self) -> int:
        """Publishes one batch and returns how many events were sent.

        The row locks are held while we talk to the broker, which is what stops a second relay
        from sending the same rows. If the broker fails midway, the events already confirmed are
        still marked as sent and committed; the rest stay unsent for the next attempt, and the
        error is raised AFTER the commit.
        """
        published: list[uuid.UUID] = []
        failure: Exception | None = None
        async with self._pool.acquire() as conn, conn.transaction():
            rows = await outbox_repository.lock_unpublished(conn, self._batch_size)
            for row in rows:
                try:
                    await self._broker.publish(
                        event_id=str(row["id"]),
                        event_type=row["event_type"],
                        body=build_body(row),
                        request_id=row["request_id"],
                    )
                except Exception as exc:
                    failure = exc
                    break
                published.append(row["id"])
            if published:
                await outbox_repository.mark_published(conn, published)

        OUTBOX_PUBLISHED.inc(len(published))  # after the commit: only what is really marked as sent
        if failure is not None:
            OUTBOX_PUBLISH_FAILURES.inc()
            raise failure
        if published:
            log.info("outbox_batch_published", count=len(published))
        return len(published)

    async def run(self, stop: asyncio.Event) -> None:
        failures = 0
        while not stop.is_set():
            try:
                sent = await self.publish_pending()
                failures = 0
            except Exception as exc:
                failures += 1
                delay = min(self._max_backoff, self._poll_interval * 2**failures)
                log.warning("outbox_publish_failed", error=repr(exc), retry_in_seconds=delay)
                await _sleep(stop, delay)
                continue
            if sent < self._batch_size:  # backlog drained: wait. A full batch means "go again".
                await _sleep(stop, self._poll_interval)


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)
