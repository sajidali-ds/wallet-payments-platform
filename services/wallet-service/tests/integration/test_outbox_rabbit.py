"""The real thing: outbox -> relay -> RabbitMQ with publisher confirms."""

import json
from uuid import uuid4

import aio_pika
import pytest

from app.outbox.rabbit import RabbitBroker
from app.outbox.relay import OutboxRelay


@pytest.fixture
async def rabbit_channel(rabbit_url):
    connection = await aio_pika.connect_robust(rabbit_url)
    channel = await connection.channel()
    yield channel
    await connection.close()


async def test_event_reaches_rabbitmq_with_publisher_confirms(
    rabbit_url, rabbit_channel, pool, new_account, transfer
):
    suffix = uuid4().hex[:8]
    exchange_name, queue_name = f"test.{suffix}.events", f"test.{suffix}.queue"
    exchange = await rabbit_channel.declare_exchange(
        exchange_name, aio_pika.ExchangeType.TOPIC, durable=True
    )
    queue = await rabbit_channel.declare_queue(queue_name, auto_delete=True)
    await queue.bind(exchange, routing_key="transfer.completed")

    alice, bob = await new_account(1000), await new_account()
    await pool.execute("DELETE FROM outbox_events")
    response = await transfer(alice, bob.wallet_id, 400, request_id="trace-rabbit-1")
    transfer_id = response.json()["transfer_id"]
    broker = RabbitBroker(rabbit_url, exchange_name)
    try:
        sent = await OutboxRelay(pool, broker).publish_pending()
        message = await queue.get(timeout=5)
    finally:
        await broker.close()
        await queue.delete()
        await exchange.delete()

    assert sent == 1
    envelope = json.loads(message.body)
    assert message.message_id == envelope["event_id"]
    assert envelope["event_type"] == "transfer.completed"
    assert envelope["data"]["transfer_id"] == transfer_id
    assert envelope["data"]["amount"] == 400
    assert message.delivery_mode == aio_pika.DeliveryMode.PERSISTENT
    assert message.correlation_id == "trace-rabbit-1"  # as an AMQP property...
    assert envelope["request_id"] == "trace-rabbit-1"  # ...and inside the event itself
    await message.ack()
    unsent = "SELECT count(*) FROM outbox_events WHERE published_at IS NULL"
    assert await pool.fetchval(unsent) == 0


async def test_unroutable_event_stays_in_the_outbox_until_a_queue_exists(
    rabbit_url, rabbit_channel, pool, new_account
):
    suffix = uuid4().hex[:8]
    exchange_name, queue_name = f"test.{suffix}.events", f"test.{suffix}.queue"
    exchange = await rabbit_channel.declare_exchange(
        exchange_name, aio_pika.ExchangeType.TOPIC, durable=True
    )  # an exchange with NO queue bound: nobody would receive the event
    await new_account(500)  # the funding deposit writes one event
    broker = RabbitBroker(rabbit_url, exchange_name)
    relay = OutboxRelay(pool, broker)
    try:
        with pytest.raises(Exception):  # noqa: B017 - the broker returns the unroutable message
            await relay.publish_pending()
        unsent = "SELECT count(*) FROM outbox_events WHERE published_at IS NULL"
        assert await pool.fetchval(unsent) == 1

        queue = await rabbit_channel.declare_queue(queue_name, auto_delete=True)
        await queue.bind(exchange, routing_key="transfer.completed")
        assert await relay.publish_pending() == 1  # now it can be delivered
        message = await queue.get(timeout=5)
        await message.ack()
    finally:
        await broker.close()
        await exchange.delete()
