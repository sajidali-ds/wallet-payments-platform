import asyncio
import contextlib
import json
import os
import re
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import aio_pika
import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from app.consumers.topology import ROUTING_KEY, Topology
from app.consumers.transfer_consumer import TransferEventConsumer
from app.db import create_pool
from app.main import create_app
from app.migrate import run_migrations


async def _ensure_database(url: str) -> None:
    """Creates the test database if missing (e.g. the Postgres volume predates it)."""
    parts = urlsplit(url)
    name = parts.path.lstrip("/")
    if not re.fullmatch(r"[a-z0-9_]+", name):
        raise RuntimeError(f"Unsafe test database name: {name!r}")
    conn = await asyncpg.connect(urlunsplit(parts._replace(path="/postgres")))
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
            await conn.execute(f'CREATE DATABASE "{name}"')  # noqa: S608 - name validated above
    finally:
        await conn.close()


async def _prepare(url: str) -> None:
    await _ensure_database(url)
    await run_migrations(url)


@pytest.fixture(scope="session", autouse=True)
def _migrated_database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        raise RuntimeError("TEST_DATABASE_URL is not set. Run the tests with `make test`.")
    asyncio.run(_prepare(url))


@pytest.fixture
async def pool():
    pool = await create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=10)
    await pool.execute("TRUNCATE notifications, processed_events")
    yield pool
    await pool.close()


@pytest.fixture
async def client(pool):
    app = create_app()
    app.state.pool = pool
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


# ---- RabbitMQ --------------------------------------------------------------------------------
@pytest.fixture
async def rabbit():
    url = os.environ.get("TEST_RABBITMQ_URL")
    if not url:
        raise RuntimeError("TEST_RABBITMQ_URL is not set. Run the tests with `make test`.")
    connection = await aio_pika.connect_robust(url)
    yield connection
    await connection.close()


@pytest.fixture
def topology() -> Topology:
    """Unique exchange and queues per test, so tests never touch each other (or a running stack)."""
    suffix = uuid4().hex[:8]
    return Topology(
        exchange=f"test.{suffix}.events",
        queue=f"test.{suffix}.notifications",
        max_retries=2,  # a message is tried 3 times in total: the first delivery + 2 retries
        retry_base_delay_ms=100,  # retry delays: 100 ms, then 200 ms
    )


@pytest.fixture
async def channel(rabbit, topology):
    channel = await rabbit.channel()
    yield channel
    queues = [topology.queue, topology.dlq]
    queues += [topology.retry_queue(n) for n in range(1, topology.max_retries + 1)]
    with contextlib.suppress(Exception):
        for name in queues:
            await channel.queue_delete(name)
        await channel.exchange_delete(topology.exchange)


@pytest.fixture
async def start_consumer(rabbit, pool, topology, channel):
    """start(handler=None) -> a consumer attached to this test's private queues."""
    consumers: list[TransferEventConsumer] = []

    async def start(handler=None, prefetch: int = 10) -> TransferEventConsumer:
        kwargs = {"prefetch_count": prefetch}
        if handler is not None:
            kwargs["handler"] = handler
        consumer = TransferEventConsumer(pool, topology, **kwargs)
        await consumer.start(rabbit)
        consumers.append(consumer)
        return consumer

    yield start
    for consumer in consumers:
        await consumer.stop()


@pytest.fixture
def make_event():
    def make(type: str = "transfer", amount: int = 1250, **data_overrides) -> dict:
        sender = None if type == "deposit" else str(uuid4())
        data = {
            "transfer_id": str(uuid4()),
            "type": type,
            "from_wallet_id": str(uuid4()),
            "from_user_id": sender,
            "to_wallet_id": str(uuid4()),
            "to_user_id": str(uuid4()),
            "amount": amount,
            "currency": "INR",
        } | data_overrides
        return {
            "event_id": str(uuid4()),
            "event_type": "transfer.completed",
            "occurred_at": "2026-11-19T10:30:00+00:00",
            "data": data,
        }

    return make


@pytest.fixture
def publish(channel, topology):
    """publish(event_or_bytes): sends to the exchange like wallet-service's relay does."""

    async def send(event: dict | bytes, request_id: str | None = None) -> None:
        exchange = await channel.declare_exchange(
            topology.exchange, aio_pika.ExchangeType.TOPIC, durable=True
        )
        body = event if isinstance(event, bytes) else json.dumps(event).encode()
        message_id = None if isinstance(event, bytes) else event["event_id"]
        message = aio_pika.Message(
            body=body,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=message_id,
            correlation_id=request_id,
        )
        await exchange.publish(message, routing_key=ROUTING_KEY, mandatory=True)

    return send


@pytest.fixture
def queue_sizes(channel, topology):
    """queue_sizes() -> {'main': n, 'retry': n, 'dlq': n}: messages currently waiting."""

    async def count(name: str) -> int:
        queue = await channel.declare_queue(name, passive=True)
        return queue.declaration_result.message_count

    async def sizes() -> dict[str, int]:
        retry = sum(
            [await count(topology.retry_queue(n)) for n in range(1, topology.max_retries + 1)]
        )
        main, dlq = await count(topology.queue), await count(topology.dlq)
        return {"main": main, "retry": retry, "dlq": dlq}

    return sizes


@pytest.fixture
def notification_rows(pool):
    async def rows(event_id: str):
        return await pool.fetch(
            "SELECT user_id::text AS user_id, type, message FROM notifications WHERE event_id = $1",
            event_id,
        )

    return rows
