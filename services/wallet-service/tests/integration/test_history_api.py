from uuid import uuid4

import pytest


@pytest.fixture
def admin(headers_for):
    return headers_for(uuid4(), "admin")


async def _new_wallet(client, headers_for):
    headers = headers_for(uuid4())
    wallet = (await client.post("/wallets", headers=headers)).json()
    return headers, wallet["id"]


async def _deposit(client, admin, wallet_id, amount):
    response = await client.post(
        f"/wallets/{wallet_id}/deposit", json={"amount": amount}, headers=admin
    )
    assert response.status_code == 201
    return response.json()


async def test_history_is_empty_for_a_new_wallet(client, headers_for):
    user, _ = await _new_wallet(client, headers_for)
    response = await client.get("/wallets/me/transactions", headers=user)
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


async def test_history_lists_newest_first_with_running_balance(client, headers_for, admin):
    user, wallet_id = await _new_wallet(client, headers_for)
    for amount in (100, 250, 650):
        await _deposit(client, admin, wallet_id, amount)

    body = (await client.get("/wallets/me/transactions", headers=user)).json()
    assert [(i["amount"], i["balance_after"]) for i in body["items"]] == [
        (650, 1000),
        (250, 350),
        (100, 100),
    ]
    assert all(i["type"] == "deposit" for i in body["items"])
    assert body["next_cursor"] is None


async def test_history_pagination_walks_every_entry_exactly_once(client, headers_for, admin):
    user, wallet_id = await _new_wallet(client, headers_for)
    for amount in (100, 200, 300, 400, 500):
        await _deposit(client, admin, wallet_id, amount)

    seen: list[int] = []
    cursor = None
    pages = 0
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        body = (await client.get("/wallets/me/transactions", params=params, headers=user)).json()
        seen += [item["amount"] for item in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert seen == [500, 400, 300, 200, 100]
    assert pages == 3


async def test_pagination_has_no_next_cursor_when_page_is_exactly_full(client, headers_for, admin):
    user, wallet_id = await _new_wallet(client, headers_for)
    for amount in (100, 200):
        await _deposit(client, admin, wallet_id, amount)
    body = (
        await client.get("/wallets/me/transactions", params={"limit": 2}, headers=user)
    ).json()
    assert len(body["items"]) == 2
    assert body["next_cursor"] is None


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"cursor": 0}, {"cursor": "x"}])
async def test_invalid_pagination_params_are_422(client, headers_for, params):
    user, _ = await _new_wallet(client, headers_for)
    response = await client.get("/wallets/me/transactions", params=params, headers=user)
    assert response.status_code == 422


async def test_history_only_contains_the_callers_entries(client, headers_for, admin):
    alice, alice_wallet = await _new_wallet(client, headers_for)
    bob, bob_wallet = await _new_wallet(client, headers_for)
    await _deposit(client, admin, alice_wallet, 700)
    await _deposit(client, admin, bob_wallet, 300)

    alice_items = (await client.get("/wallets/me/transactions", headers=alice)).json()["items"]
    bob_items = (await client.get("/wallets/me/transactions", headers=bob)).json()["items"]
    assert [i["amount"] for i in alice_items] == [700]
    assert [i["amount"] for i in bob_items] == [300]


async def test_history_requires_authentication(client):
    assert (await client.get("/wallets/me/transactions")).status_code == 401
