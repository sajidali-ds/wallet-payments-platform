import asyncio
import contextlib

import aio_pika
import structlog

from app.consumers.transfer_consumer import TransferEventConsumer

log = structlog.get_logger()


async def run_consumer(
    consumer: TransferEventConsumer,
    rabbitmq_url: str,
    stop: asyncio.Event,
    *,
    reconnect_delay: float = 2.0,
) -> None:
    """Keeps the consumer attached to RabbitMQ until `stop` is set.

    connect_robust re-establishes the connection and the consumer after a broker restart by
    itself; this loop additionally covers the case where the FIRST connection fails (broker not
    up yet), so the service can start before RabbitMQ is ready.
    """
    while not stop.is_set():
        connection = None
        try:
            connection = await aio_pika.connect_robust(rabbitmq_url)
            await consumer.start(connection)
            log.info("consumer_started")
            await stop.wait()
        except Exception:
            log.exception("consumer_connection_failed", retry_in_seconds=reconnect_delay)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=reconnect_delay)
        finally:
            await consumer.stop()
            if connection is not None:
                with contextlib.suppress(Exception):
                    await connection.close()
    log.info("consumer_stopped")
