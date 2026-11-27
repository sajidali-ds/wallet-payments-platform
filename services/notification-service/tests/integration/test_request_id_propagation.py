"""The request id travels in the message's correlation_id and shows up in the consumer's logs."""

import structlog

from app.services.notification_service import handle_transfer_completed


def _capturing_handler(seen: list):
    async def handler(pool, event):
        seen.append(structlog.contextvars.get_contextvars().get("request_id"))
        return await handle_transfer_completed(pool, event)

    return handler


async def test_request_id_is_in_the_logging_context_while_the_event_is_handled(
    start_consumer, publish, make_event, eventually
):
    seen: list = []
    consumer = await start_consumer(_capturing_handler(seen))

    await publish(make_event(), request_id="trace-xyz-1")
    await eventually(lambda: consumer.stats.acked == 1)

    assert seen == ["trace-xyz-1"]


async def test_events_without_a_request_id_are_still_handled(
    start_consumer, publish, make_event, eventually
):
    seen: list = []
    consumer = await start_consumer(_capturing_handler(seen))

    await publish(make_event())  # e.g. an event from an older producer
    await eventually(lambda: consumer.stats.acked == 1)

    assert seen == [None]
    assert consumer.stats.processed == 1


async def test_request_id_survives_every_retry_and_the_dead_letter_queue(
    start_consumer, publish, make_event, channel, topology, eventually
):
    seen: list = []

    async def always_failing(pool, event):
        seen.append(structlog.contextvars.get_contextvars().get("request_id"))
        raise ConnectionError("downstream is broken")

    consumer = await start_consumer(always_failing)
    await publish(make_event(), request_id="trace-dlq-7")
    await eventually(lambda: consumer.stats.dead_lettered == 1)
    await eventually(lambda: consumer.stats.acked == 3)

    assert seen == ["trace-dlq-7"] * 3  # first delivery and both retries

    dlq = await channel.declare_queue(topology.dlq, passive=True)
    parked = await dlq.get(timeout=5)
    assert parked.correlation_id == "trace-dlq-7"  # a human triaging the DLQ can find the request
    await parked.ack()
