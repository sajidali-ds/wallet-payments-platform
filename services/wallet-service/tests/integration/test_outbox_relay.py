"""Relay behaviour against a real Postgres, with an in-memory fake broker."""

import asyncio
import json

import pytest

from app.outbox.relay import OutboxRelay
from app.repositories import outbox_repository


class FakeBroker:
    def __init__(self, *, fail_from_call: int | None = None, delay: float = 0.0) -> None:
        self.fail_from_call = fail_from_call  # every call numbered >= this raises
        self.delay = delay
        self.calls = 0
        self.published: list[tuple[str, str, dict]] = []
        self.request_ids: list[str | None] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def publish(
        self, *, event_id: str, event_type: str, body: bytes, request_id: str | None = None
    ) -> None:
        self.calls += 1
        if self.fail_from_call is not None and self.calls >= self.fail_from_call:
            raise ConnectionError("broker down")
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.in_flight -= 1
        self.published.append((event_id, event_type, json.loads(body)))
        self.request_ids.append(request_id)

    @property
    def published_ids(self) -> list[str]:
        return [event_id for event_id, _, _ in self.published]


async def _seed(pool, count: int) -> list[str]:
    ids = []
    for n in range(count):
        ids.append(await outbox_repository.add_event(pool, "transfer.completed", {"n": n}))
    return [str(i) for i in ids]


async def _unpublished(pool) -> int:
    return await pool.fetchval("SELECT count(*) FROM outbox_events WHERE published_at IS NULL")


async def test_publishes_pending_events_and_marks_them_sent(pool):
    ids = await _seed(pool, 3)
    broker = FakeBroker()
    relay = OutboxRelay(pool, broker, batch_size=10)

    assert await relay.publish_pending() == 3

    assert set(broker.published_ids) == set(ids)
    event_id, event_type, envelope = broker.published[0]
    assert event_type == "transfer.completed"
    assert envelope["event_id"] == event_id  # consumers dedupe on this
    assert envelope["data"] == {"n": 0}
    assert await _unpublished(pool) == 0
    assert await relay.publish_pending() == 0  # nothing left: nothing is sent twice


async def test_events_are_sent_in_batches(pool):
    await _seed(pool, 5)
    relay = OutboxRelay(pool, FakeBroker(), batch_size=2)
    assert [await relay.publish_pending() for _ in range(4)] == [2, 2, 1, 0]


async def test_broker_failure_midway_keeps_unsent_events_and_loses_nothing(pool):
    ids = await _seed(pool, 5)
    broker = FakeBroker(fail_from_call=3)  # the 3rd publish raises
    relay = OutboxRelay(pool, broker, batch_size=10)

    with pytest.raises(ConnectionError):
        await relay.publish_pending()

    # The two confirmed events were committed as sent; the other three are still waiting.
    assert await _unpublished(pool) == 3
    assert len(broker.published) == 2

    broker.fail_from_call = None  # the broker comes back
    assert await relay.publish_pending() == 3
    assert sorted(broker.published_ids) == sorted(ids)  # every event sent exactly once
    assert await _unpublished(pool) == 0


async def test_broker_down_from_the_start_leaves_everything_unsent(pool):
    ids = await _seed(pool, 3)
    broker = FakeBroker(fail_from_call=1)
    relay = OutboxRelay(pool, broker, batch_size=10)

    with pytest.raises(ConnectionError):
        await relay.publish_pending()
    assert await _unpublished(pool) == 3

    broker.fail_from_call = None
    assert await relay.publish_pending() == 3
    assert sorted(broker.published_ids) == sorted(ids)


async def test_two_relays_share_the_backlog_without_blocking_or_duplicates(pool):
    # SKIP LOCKED: while relay 1 holds the first 10 rows, relay 2 takes the NEXT 10 immediately
    # instead of waiting. With plain FOR UPDATE they would run one after the other.
    ids = await _seed(pool, 20)
    broker = FakeBroker(delay=0.25)
    relay_1 = OutboxRelay(pool, broker, batch_size=10)
    relay_2 = OutboxRelay(pool, broker, batch_size=10)

    sent = await asyncio.gather(relay_1.publish_pending(), relay_2.publish_pending())

    assert sorted(sent) == [10, 10]
    assert sorted(broker.published_ids) == sorted(ids)  # no event sent twice
    assert broker.max_in_flight == 2  # they really did publish at the same time


async def test_run_loop_drains_the_outbox_and_recovers_from_a_broker_outage(pool, eventually):
    ids = await _seed(pool, 3)
    broker = FakeBroker(fail_from_call=1)  # broker is down at first
    relay = OutboxRelay(pool, broker, batch_size=10, poll_interval=0.05, max_backoff=0.2)
    stop = asyncio.Event()
    task = asyncio.create_task(relay.run(stop))

    asyncio.get_running_loop().call_later(0.3, setattr, broker, "fail_from_call", None)
    await eventually(lambda: len(broker.published) == 3)

    stop.set()
    await asyncio.wait_for(task, timeout=5)
    assert sorted(broker.published_ids) == sorted(ids)
    assert await _unpublished(pool) == 0
