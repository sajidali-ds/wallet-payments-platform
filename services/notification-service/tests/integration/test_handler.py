"""Idempotent event handling, against a real Postgres (no RabbitMQ needed)."""

import asyncio

import pytest

from app.repositories import notification_repository
from app.schemas.event import EventEnvelope
from app.services.notification_service import handle_transfer_completed


async def _handle(pool, event: dict) -> bool:
    return await handle_transfer_completed(pool, EventEnvelope.model_validate(event))


async def test_transfer_event_creates_a_notification_for_each_side(
    pool, make_event, notification_rows
):
    event = make_event(amount=1250)
    assert await _handle(pool, event) is True

    rows = await notification_rows(event["event_id"])
    by_type = {r["type"]: r for r in rows}
    assert by_type["transfer.received"]["user_id"] == event["data"]["to_user_id"]
    assert by_type["transfer.received"]["message"] == "You received INR 12.50"
    assert by_type["transfer.sent"]["user_id"] == event["data"]["from_user_id"]
    assert await pool.fetchval("SELECT count(*) FROM processed_events") == 1


async def test_deposit_event_creates_one_notification(pool, make_event, notification_rows):
    event = make_event(type="deposit", amount=500_000)
    await _handle(pool, event)

    rows = await notification_rows(event["event_id"])
    assert [(r["type"], r["message"]) for r in rows] == [
        ("deposit.received", "INR 5,000.00 was deposited into your wallet")
    ]


async def test_the_same_event_delivered_twice_is_handled_once(pool, make_event, notification_rows):
    event = make_event()
    assert await _handle(pool, event) is True
    assert await _handle(pool, event) is False  # duplicate delivery: recognised and skipped

    assert len(await notification_rows(event["event_id"])) == 2  # not 4
    assert await pool.fetchval("SELECT count(*) FROM processed_events") == 1


async def test_ten_concurrent_deliveries_of_one_event_are_handled_once(
    pool, make_event, notification_rows
):
    event = make_event()
    results = await asyncio.gather(*[_handle(pool, event) for _ in range(10)])

    assert results.count(True) == 1
    assert results.count(False) == 9
    assert len(await notification_rows(event["event_id"])) == 2


async def test_different_events_are_independent(pool, make_event):
    assert await _handle(pool, make_event()) is True
    assert await _handle(pool, make_event()) is True
    assert await pool.fetchval("SELECT count(*) FROM processed_events") == 2


async def test_failure_midway_leaves_no_processed_marker_so_a_retry_can_succeed(
    pool, make_event, notification_rows, monkeypatch
):
    event = make_event()
    real_insert = notification_repository.insert
    calls = 0

    async def insert_that_fails_the_second_time(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("database hiccup")
        await real_insert(*args, **kwargs)

    monkeypatch.setattr(notification_repository, "insert", insert_that_fails_the_second_time)
    with pytest.raises(RuntimeError):
        await _handle(pool, event)

    # One notification was already inserted when the failure hit, yet nothing is visible:
    # the marker and the notifications share a transaction, so all of it rolled back.
    assert await notification_rows(event["event_id"]) == []
    assert await pool.fetchval("SELECT count(*) FROM processed_events") == 0

    monkeypatch.setattr(notification_repository, "insert", real_insert)
    assert await _handle(pool, event) is True  # the redelivery does the full job
    assert len(await notification_rows(event["event_id"])) == 2
