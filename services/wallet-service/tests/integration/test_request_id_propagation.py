"""gateway -> wallet-service -> outbox event -> broker message: one request id all the way."""

import json
from uuid import uuid4

from app.outbox.relay import OutboxRelay


class RecordingBroker:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def publish(self, *, event_id: str, event_type: str, body: bytes, request_id=None):
        self.calls.append({"request_id": request_id, "envelope": json.loads(body)})


async def _stored_request_ids(pool) -> list[str | None]:
    rows = await pool.fetch("SELECT request_id FROM outbox_events ORDER BY created_at, id")
    return [row["request_id"] for row in rows]


async def test_request_id_reaches_the_event_and_the_message_envelope(new_account, transfer, pool):
    alice, bob = await new_account(1000), await new_account()
    await pool.execute("DELETE FROM outbox_events")

    response = await transfer(alice, bob.wallet_id, 100, request_id="trace-abc-123")

    assert response.headers["x-request-id"] == "trace-abc-123"  # echoed to the caller
    assert await _stored_request_ids(pool) == ["trace-abc-123"]  # saved with the event

    broker = RecordingBroker()
    await OutboxRelay(pool, broker).publish_pending()
    assert broker.calls[0]["request_id"] == "trace-abc-123"  # handed to the broker
    assert broker.calls[0]["envelope"]["request_id"] == "trace-abc-123"  # and part of the event


async def test_a_generated_request_id_is_stored_when_the_caller_sends_none(
    new_account, transfer, pool
):
    alice, bob = await new_account(1000), await new_account()
    await pool.execute("DELETE FROM outbox_events")

    response = await transfer(alice, bob.wallet_id, 100)

    generated = response.headers["x-request-id"]
    assert len(generated) == 32
    assert await _stored_request_ids(pool) == [generated]


async def test_an_unsafe_incoming_request_id_is_replaced_not_stored(new_account, transfer, pool):
    alice, bob = await new_account(1000), await new_account()
    await pool.execute("DELETE FROM outbox_events")

    response = await transfer(alice, bob.wallet_id, 100, request_id="bad id; DROP TABLE")

    replaced = response.headers["x-request-id"]
    assert replaced != "bad id; DROP TABLE"
    assert await _stored_request_ids(pool) == [replaced]


async def test_deposit_events_carry_the_request_id_too(client, new_account, headers_for, pool):
    bob = await new_account()
    await pool.execute("DELETE FROM outbox_events")

    response = await client.post(
        f"/wallets/{bob.wallet_id}/deposit",
        json={"amount": 500},
        headers={**headers_for(uuid4(), "admin"), "X-Request-ID": "trace-deposit-9"},
    )

    assert response.status_code == 201
    assert await _stored_request_ids(pool) == ["trace-deposit-9"]


async def test_every_request_gets_its_own_id(new_account, transfer, pool):
    alice, bob = await new_account(1000), await new_account()
    await pool.execute("DELETE FROM outbox_events")

    await transfer(alice, bob.wallet_id, 10, request_id="trace-one")
    await transfer(alice, bob.wallet_id, 10, request_id="trace-two")

    assert sorted(await _stored_request_ids(pool)) == ["trace-one", "trace-two"]
