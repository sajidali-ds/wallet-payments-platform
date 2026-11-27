from uuid import uuid4

from app.schemas.event import EventEnvelope
from app.services.notification_service import handle_transfer_completed


async def _deliver(pool, event: dict) -> None:
    await handle_transfer_completed(pool, EventEnvelope.model_validate(event))


async def test_user_sees_only_their_own_notifications(client, pool, make_event, headers_for):
    alice, bob = uuid4(), uuid4()
    await _deliver(pool, make_event(to_user_id=str(alice), from_user_id=str(bob), amount=1000))

    alice_items = (await client.get("/notifications", headers=headers_for(alice))).json()["items"]
    bob_items = (await client.get("/notifications", headers=headers_for(bob))).json()["items"]
    assert [i["type"] for i in alice_items] == ["transfer.received"]
    assert [i["type"] for i in bob_items] == ["transfer.sent"]
    assert (await client.get("/notifications", headers=headers_for(uuid4()))).json()["items"] == []


async def test_notifications_are_paginated_newest_first(client, pool, make_event, headers_for):
    alice = uuid4()
    for amount in (100, 200, 300, 400, 500):
        await _deliver(pool, make_event(type="deposit", to_user_id=str(alice), amount=amount))
    headers = headers_for(alice)

    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        body = (await client.get("/notifications", params=params, headers=headers)).json()
        seen += [item["message"] for item in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert pages == 3
    assert seen == [
        "INR 5.00 was deposited into your wallet",
        "INR 4.00 was deposited into your wallet",
        "INR 3.00 was deposited into your wallet",
        "INR 2.00 was deposited into your wallet",
        "INR 1.00 was deposited into your wallet",
    ]


async def test_notifications_require_authentication(client):
    assert (await client.get("/notifications")).status_code == 401
