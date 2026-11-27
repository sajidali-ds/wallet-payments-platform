"""The outbox event is written in the SAME transaction as the money movement."""

import asyncio
import json

import pytest

from app.repositories import outbox_repository


async def _events(pool):
    return await pool.fetch(
        """
        SELECT id::text AS id, event_type, payload::text AS payload, published_at
        FROM outbox_events ORDER BY created_at, id
        """
    )


async def test_transfer_writes_exactly_one_transfer_completed_event(new_account, transfer, pool):
    alice, bob = await new_account(1000), await new_account()
    await pool.execute("DELETE FROM outbox_events")  # forget the events of the funding deposit

    body = (await transfer(alice, bob.wallet_id, 400)).json()

    events = await _events(pool)
    assert len(events) == 1
    assert events[0]["event_type"] == "transfer.completed"
    assert events[0]["published_at"] is None  # the relay has not run: it is waiting in the outbox
    assert json.loads(events[0]["payload"]) == {
        "transfer_id": body["transfer_id"],
        "type": "transfer",
        "from_wallet_id": alice.wallet_id,
        "from_user_id": alice.user_id,
        "to_wallet_id": bob.wallet_id,
        "to_user_id": bob.user_id,
        "amount": 400,
        "currency": "INR",
    }


async def test_deposit_writes_an_event_without_a_sender_user(new_account, pool):
    bob = await new_account(500)  # funding goes through the admin deposit endpoint

    events = await _events(pool)
    assert len(events) == 1
    data = json.loads(events[0]["payload"])
    assert data["type"] == "deposit"
    assert data["from_user_id"] is None  # the system wallet has no user
    assert data["to_user_id"] == bob.user_id
    assert data["amount"] == 500


async def test_failed_transfer_writes_no_event(new_account, transfer, pool):
    alice, bob = await new_account(100), await new_account()
    await pool.execute("DELETE FROM outbox_events")

    assert (await transfer(alice, bob.wallet_id, 101)).status_code == 422  # insufficient funds

    assert await _events(pool) == []


async def test_replayed_request_does_not_write_a_second_event(new_account, transfer, pool):
    alice, bob = await new_account(1000), await new_account()
    await pool.execute("DELETE FROM outbox_events")

    await transfer(alice, bob.wallet_id, 100, key="k")
    await transfer(alice, bob.wallet_id, 100, key="k")

    assert len(await _events(pool)) == 1


async def test_concurrent_duplicate_requests_write_one_event(new_account, transfer, pool):
    alice, bob = await new_account(1000), await new_account()
    await pool.execute("DELETE FROM outbox_events")

    await asyncio.gather(*[transfer(alice, bob.wallet_id, 100, key="same") for _ in range(10)])

    assert len(await _events(pool)) == 1


async def test_100_parallel_transfers_write_100_events_one_per_transfer(
    new_account, transfer, pool
):
    alice, bob = await new_account(10_000), await new_account()
    await pool.execute("DELETE FROM outbox_events")

    await asyncio.gather(*[transfer(alice, bob.wallet_id, 100) for _ in range(100)])

    rows = await pool.fetch("SELECT id::text AS id FROM transfers WHERE type = 'transfer'")
    transfer_ids = {row["id"] for row in rows}
    event_transfer_ids = [json.loads(e["payload"])["transfer_id"] for e in await _events(pool)]
    assert len(event_transfer_ids) == 100
    assert set(event_transfer_ids) == transfer_ids  # each transfer has exactly one event


async def test_money_does_not_move_if_the_event_cannot_be_written(
    monkeypatch, new_account, transfer, balance_of, pool
):
    alice, bob = await new_account(1000), await new_account()

    async def broken_add_event(*args, **kwargs):
        raise RuntimeError("outbox write failed")

    monkeypatch.setattr(outbox_repository, "add_event", broken_add_event)

    with pytest.raises(RuntimeError):
        await transfer(alice, bob.wallet_id, 400)

    # Same transaction: the failed event write rolled the whole transfer back.
    assert await balance_of(alice) == 1000
    assert await balance_of(bob) == 0
    assert await pool.fetchval("SELECT count(*) FROM transfers WHERE type = 'transfer'") == 0
