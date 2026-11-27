import asyncio

from prometheus_client import REGISTRY

from app.routers.metrics import refresh_queue_gauges
from app.services.notification_service import handle_transfer_completed


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_outcomes_are_counted(start_consumer, publish, make_event, eventually):
    processed = sample("notification_events_total", outcome="processed")
    duplicate = sample("notification_events_total", outcome="duplicate")
    consumer = await start_consumer()
    event = make_event()

    await publish(event)
    await publish(event)  # delivered twice
    await eventually(lambda: consumer.stats.acked == 2)

    assert sample("notification_events_total", outcome="processed") - processed == 1
    assert sample("notification_events_total", outcome="duplicate") - duplicate == 1


async def test_retries_and_dead_letters_are_counted(
    start_consumer, publish, make_event, eventually
):
    retried = sample("notification_events_total", outcome="retried")
    dead = sample("notification_events_total", outcome="dead_lettered")

    async def always_failing(pool, event):
        raise ConnectionError("downstream is broken")

    consumer = await start_consumer(always_failing)
    await publish(make_event())
    await eventually(lambda: consumer.stats.dead_lettered == 1)

    assert sample("notification_events_total", outcome="retried") - retried == 2
    assert sample("notification_events_total", outcome="dead_lettered") - dead == 1


async def test_queue_depth_gauge_shows_the_backlog_and_drains(
    start_consumer, publish, make_event, eventually
):
    gate, entered = asyncio.Event(), asyncio.Event()

    async def blocked_handler(pool, event):
        entered.set()
        await gate.wait()
        await handle_transfer_completed(pool, event)

    consumer = await start_consumer(blocked_handler, prefetch=1)

    for _ in range(4):
        await publish(make_event())

    await asyncio.wait_for(entered.wait(), timeout=10)

    async def main_queue_holds_three() -> bool:
        await refresh_queue_gauges(consumer)
        return sample("notification_queue_depth", queue="main") == 3

    await eventually(main_queue_holds_three)
    assert sample("notification_consumer_connected") == 1

    gate.set()
    await eventually(lambda: consumer.stats.acked == 4)

    async def main_queue_empty() -> bool:
        await refresh_queue_gauges(consumer)
        return sample("notification_queue_depth", queue="main") == 0

    await eventually(main_queue_empty)


async def test_dead_letter_queue_depth_is_reported(start_consumer, publish, eventually):
    consumer = await start_consumer()
    await publish(b"this is not json")  # poison: goes straight to the dead-letter queue
    await eventually(lambda: consumer.stats.acked == 1)

    async def dlq_holds_one() -> bool:
        await refresh_queue_gauges(consumer)
        return sample("notification_queue_depth", queue="dlq") == 1

    await eventually(dlq_holds_one)
