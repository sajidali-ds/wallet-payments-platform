"""The consumer against a real RabbitMQ: success, retry, dead-letter and duplicate paths.

Retry delays in these tests are 100 ms then 200 ms (see the `topology` fixture), and each test
uses its own exchange and queues.
"""

import json
import time

import pytest

from app.services.notification_service import handle_transfer_completed


async def _stop_and_sizes(consumer, queue_sizes) -> dict[str, int]:
    """Stops the consumer first: a message that was received but never acked goes back to its
    queue and shows up in the count, so an all-zero result really means 'everything was acked'."""
    await consumer.stop()
    return await queue_sizes()


# ---- success path ----------------------------------------------------------------------------
async def test_event_is_consumed_and_notifications_are_created(
    start_consumer, publish, make_event, notification_rows, queue_sizes, eventually
):
    consumer = await start_consumer()
    event = make_event(amount=1250)

    await publish(event)
    await eventually(lambda: consumer.stats.acked == 1)

    rows = await notification_rows(event["event_id"])
    assert sorted(r["type"] for r in rows) == ["transfer.received", "transfer.sent"]
    assert consumer.stats.processed == 1
    assert (consumer.stats.retried, consumer.stats.dead_lettered) == (0, 0)
    assert await _stop_and_sizes(consumer, queue_sizes) == {"main": 0, "retry": 0, "dlq": 0}


# ---- duplicate delivery ----------------------------------------------------------------------
async def test_duplicate_delivery_of_the_same_event_is_acked_but_processed_once(
    start_consumer, publish, make_event, notification_rows, queue_sizes, pool, eventually
):
    results: list[bool] = []

    async def recording_handler(pool, event):
        results.append(await handle_transfer_completed(pool, event))

    consumer = await start_consumer(recording_handler)
    event = make_event()

    await publish(event)
    await publish(event)  # at-least-once delivery: the broker (or our relay) sent it twice
    await eventually(lambda: consumer.stats.acked == 2)

    assert sorted(results) == [False, True]  # one real run, one recognised duplicate
    assert len(await notification_rows(event["event_id"])) == 2  # not 4
    assert await pool.fetchval("SELECT count(*) FROM processed_events") == 1
    # A duplicate is not an error: no retry, no dead-lettering.
    assert (consumer.stats.retried, consumer.stats.dead_lettered) == (0, 0)
    assert await _stop_and_sizes(consumer, queue_sizes) == {"main": 0, "retry": 0, "dlq": 0}


# ---- retry path ------------------------------------------------------------------------------
async def test_transient_failures_are_retried_with_backoff_then_succeed(
    start_consumer, publish, make_event, notification_rows, queue_sizes, eventually
):
    attempts = 0

    async def flaky_handler(pool, event):
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise ConnectionError("database temporarily unavailable")
        await handle_transfer_completed(pool, event)

    consumer = await start_consumer(flaky_handler)
    event = make_event()

    started = time.monotonic()
    await publish(event)
    await eventually(lambda: consumer.stats.processed == 1)
    elapsed = time.monotonic() - started

    assert attempts == 3  # first delivery + two retries
    assert consumer.stats.retried == 2
    assert consumer.stats.dead_lettered == 0
    # Backoff: the two retries waited 100 ms and 200 ms in their TTL queues. A message can never
    # leave a TTL queue early, so this lower bound is safe (an upper bound would be flaky).
    assert elapsed >= 0.28
    assert len(await notification_rows(event["event_id"])) == 2  # created exactly once
    await eventually(lambda: consumer.stats.acked == 3)  # 3 deliveries, each acked
    assert await _stop_and_sizes(consumer, queue_sizes) == {"main": 0, "retry": 0, "dlq": 0}


# ---- dead-letter path ------------------------------------------------------------------------
async def test_message_that_keeps_failing_ends_in_the_dead_letter_queue(
    start_consumer,
    publish,
    make_event,
    notification_rows,
    queue_sizes,
    channel,
    topology,
    eventually,
):
    attempts = 0

    async def always_failing_handler(pool, event):
        nonlocal attempts
        attempts += 1
        raise ConnectionError("downstream is permanently broken")

    consumer = await start_consumer(always_failing_handler)
    event = make_event()

    await publish(event)
    await eventually(lambda: consumer.stats.dead_lettered == 1)
    await eventually(lambda: consumer.stats.acked == 3)

    assert attempts == 3  # first delivery + max_retries (2) retries, then it is parked
    assert consumer.stats.retried == 2
    assert await notification_rows(event["event_id"]) == []

    sizes = await _stop_and_sizes(consumer, queue_sizes)
    assert sizes == {"main": 0, "retry": 0, "dlq": 1}  # nothing lost, nothing looping

    dlq = await channel.declare_queue(topology.dlq, passive=True)
    parked = await dlq.get(timeout=5)
    assert json.loads(parked.body) == event  # the original message, untouched
    assert parked.message_id == event["event_id"]
    assert parked.headers["x-retry-count"] == 2
    assert "retries exhausted" in parked.headers["x-error"]
    assert "permanently broken" in parked.headers["x-error"]
    await parked.ack()


@pytest.mark.parametrize(
    "body",
    [
        b"this is not json",
        b'{"event_id": "not-a-uuid"}',
        json.dumps({"event_id": "6f1c9d1e-0000-4000-8000-000000000000"}).encode(),
    ],
)
async def test_poison_message_goes_straight_to_the_dead_letter_queue(
    start_consumer, publish, queue_sizes, channel, topology, eventually, body
):
    handler_calls = 0

    async def handler(pool, event):
        nonlocal handler_calls
        handler_calls += 1

    consumer = await start_consumer(handler)

    await publish(body)
    await eventually(lambda: consumer.stats.dead_lettered == 1)
    await eventually(lambda: consumer.stats.acked == 1)

    assert handler_calls == 0  # it never reached the business logic
    assert consumer.stats.retried == 0  # and was not retried: retrying cannot fix a bad message
    assert await _stop_and_sizes(consumer, queue_sizes) == {"main": 0, "retry": 0, "dlq": 1}

    dlq = await channel.declare_queue(topology.dlq, passive=True)
    parked = await dlq.get(timeout=5)
    assert parked.body == body
    assert parked.headers["x-retry-count"] == 0
    assert "poison message" in parked.headers["x-error"]
    await parked.ack()


# ---- end to end through the real handler -----------------------------------------------------
async def test_a_failed_attempt_does_not_leave_a_dedupe_marker_behind(
    start_consumer, publish, make_event, notification_rows, pool, eventually
):
    # The handler writes its marker and the notifications in one transaction, so when an attempt
    # fails after partly working, the retry must still be able to complete the whole job.
    attempts = 0

    async def fails_after_marking(pool, event):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            async with pool.acquire() as conn, conn.transaction():
                await conn.execute(
                    "INSERT INTO processed_events (event_id, event_type) VALUES ($1, 'x')",
                    event.event_id,
                )
                raise RuntimeError("crashed after writing the marker")  # rolls the transaction back
        await handle_transfer_completed(pool, event)

    consumer = await start_consumer(fails_after_marking)
    event = make_event()

    await publish(event)
    await eventually(lambda: consumer.stats.processed == 1)

    assert attempts == 2
    assert len(await notification_rows(event["event_id"])) == 2
    assert await pool.fetchval("SELECT count(*) FROM processed_events") == 1
