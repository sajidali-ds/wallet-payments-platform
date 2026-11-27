from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import aio_pika
import asyncpg
import structlog
from aio_pika.abc import (
    AbstractChannel,
    AbstractIncomingMessage,
    AbstractQueue,
    AbstractRobustConnection,
)
from pydantic import ValidationError

from app.consumers.topology import Topology, declare_topology
from app.metrics import EVENTS
from app.schemas.event import EventEnvelope
from app.services.notification_service import handle_transfer_completed

log = structlog.get_logger()

Handler = Callable[[asyncpg.Pool, EventEnvelope], Awaitable[object]]


class PoisonMessage(Exception):
    """The message can never be processed (bad JSON, wrong shape). Retrying cannot help."""


@dataclass
class ConsumerStats:
    """Plain counters: handy in tests, and mirrored into Prometheus metrics."""

    processed: int = 0
    retried: int = 0
    dead_lettered: int = 0
    acked: int = 0


def _short(text: str, limit: int = 500) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def parse_event(body: bytes) -> EventEnvelope:
    try:
        return EventEnvelope.model_validate_json(body)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise PoisonMessage(f"{first['loc']}: {first['msg']}") from exc


class TransferEventConsumer:
    def __init__(
        self,
        pool: asyncpg.Pool,
        topology: Topology,
        *,
        prefetch_count: int = 10,
        handler: Handler = handle_transfer_completed,
    ) -> None:
        self._pool = pool
        self._topology = topology
        self._prefetch_count = prefetch_count
        self._handler = handler
        self._channel: AbstractChannel | None = None
        self._metrics_channel: AbstractChannel | None = None
        self._queue: AbstractQueue | None = None
        self._consumer_tag: str | None = None
        self.stats = ConsumerStats()

    @property
    def is_running(self) -> bool:
        return self._consumer_tag is not None

    async def start(self, connection: AbstractRobustConnection) -> None:
        self._channel = await connection.channel()  # publisher confirms are on by default
        # Prefetch: the broker sends at most this many unacknowledged messages at a time, so one
        # slow consumer cannot hoard the whole queue.
        await self._channel.set_qos(prefetch_count=self._prefetch_count)
        self._queue = await declare_topology(self._channel, self._topology)
        # A separate channel for queue-depth checks: a failed check closes ITS channel, never the
        # one that is consuming.
        self._metrics_channel = await connection.channel()
        # no_ack=False (default): MANUAL acknowledgements. A message the broker has not seen an
        # ack for is redelivered if we crash, so nothing is lost between "received" and "done".
        self._consumer_tag = await self._queue.consume(self._on_message)

    async def stop(self) -> None:
        queue, tag = self._queue, self._consumer_tag
        channel, metrics_channel = self._channel, self._metrics_channel
        self._queue = self._channel = self._metrics_channel = self._consumer_tag = None
        try:
            if queue is not None and tag is not None:
                await queue.cancel(tag)
            if channel is not None:
                await channel.close()  # unacked messages go back to the queue
            if metrics_channel is not None:
                await metrics_channel.close()
        except Exception:
            log.warning("consumer_stop_failed", exc_info=True)

    async def queue_depths(self) -> dict[str, int] | None:
        """Messages waiting in the main, retry and dead-letter queues, or None if unknown.

        Uses a passive declare, which reports READY messages only: the few messages currently
        being processed (unacked, at most `prefetch_count`) are not included.
        """
        channel = self._metrics_channel
        if channel is None:
            return None
        topology = self._topology
        try:
            retry = 0
            for attempt in range(1, topology.max_retries + 1):
                retry += await _ready_messages(channel, topology.retry_queue(attempt))
            return {
                "main": await _ready_messages(channel, topology.queue),
                "retry": retry,
                "dlq": await _ready_messages(channel, topology.dlq),
            }
        except Exception:
            log.warning("queue_depth_check_failed", exc_info=True)
            return None

    # ---- message handling --------------------------------------------------------------------
    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        # correlation_id carries the request id of the HTTP request that caused the event, so
        # every log line below can be joined with the request's logs in the other services.
        structlog.contextvars.bind_contextvars(
            message_id=message.message_id, request_id=message.correlation_id
        )
        try:
            await self._process(message)
        except Exception:
            # We could not even record the outcome (e.g. the broker dropped while republishing).
            # Hand the message back: it is redelivered, and dedupe makes the repeat harmless.
            log.exception("consumer_unexpected_error")
            try:
                await message.nack(requeue=True)
            except Exception:
                log.warning("nack_failed", exc_info=True)
        finally:
            structlog.contextvars.unbind_contextvars("message_id", "request_id")

    async def _process(self, message: AbstractIncomingMessage) -> None:
        retry_count = int((message.headers or {}).get("x-retry-count", 0))
        try:
            event = parse_event(message.body)
            result = await self._handler(self._pool, event)
        except PoisonMessage as exc:
            await self._dead_letter(message, retry_count, f"poison message: {exc}")
        except Exception as exc:
            if retry_count >= self._topology.max_retries:
                await self._dead_letter(message, retry_count, f"retries exhausted: {exc!r}")
            else:
                await self._schedule_retry(message, retry_count + 1, exc)
        else:
            self.stats.processed += 1
            # The real handler returns False for a duplicate delivery it recognised and skipped.
            EVENTS.labels(outcome="duplicate" if result is False else "processed").inc()
        # Reached only when the outcome is safely recorded: the DB commit succeeded, OR the copy
        # for the retry/dead-letter queue was confirmed by the broker. Only now do we ack.
        # If we crash between the two steps the original is redelivered: a harmless duplicate.
        await message.ack()
        self.stats.acked += 1

    async def _schedule_retry(
        self, message: AbstractIncomingMessage, attempt: int, error: Exception
    ) -> None:
        log.warning(
            "event_retry_scheduled",
            attempt=attempt,
            delay_ms=self._topology.retry_delay_ms(attempt),
            error=repr(error),
        )
        await self._republish(
            message,
            self._topology.retry_queue(attempt),
            {"x-retry-count": attempt, "x-last-error": _short(repr(error))},
        )
        self.stats.retried += 1
        EVENTS.labels(outcome="retried").inc()

    async def _dead_letter(
        self, message: AbstractIncomingMessage, retry_count: int, reason: str
    ) -> None:
        log.error("event_dead_lettered", retry_count=retry_count, reason=reason)
        await self._republish(
            message,
            self._topology.dlq,
            {
                "x-retry-count": retry_count,
                "x-error": _short(reason),
                "x-failed-at": datetime.now(UTC).isoformat(),
            },
        )
        self.stats.dead_lettered += 1
        EVENTS.labels(outcome="dead_lettered").inc()

    async def _republish(
        self, message: AbstractIncomingMessage, queue_name: str, headers: dict[str, object]
    ) -> None:
        assert self._channel is not None  # noqa: S101 - only called while running
        copy = aio_pika.Message(
            body=message.body,
            headers=headers,
            content_type=message.content_type,
            message_id=message.message_id,
            correlation_id=message.correlation_id,  # the request id survives retries and the DLQ
            type=message.type,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        # The default exchange routes by queue name. Publisher confirms make this call wait until
        # the broker has the copy, and mandatory=True turns "queue does not exist" into an error.
        await self._channel.default_exchange.publish(copy, routing_key=queue_name, mandatory=True)


async def _ready_messages(channel: AbstractChannel, queue_name: str) -> int:
    queue = await channel.declare_queue(
        queue_name,
        passive=True,
        robust=False,
    )
    return queue.declaration_result.message_count
