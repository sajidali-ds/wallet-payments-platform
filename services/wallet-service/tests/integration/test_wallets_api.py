import asyncio
from uuid import uuid4


async def test_create_wallet(client, headers_for):
    user_id = uuid4()
    response = await client.post("/wallets", headers=headers_for(user_id))
    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == str(user_id)
    assert body["currency"] == "INR"
    assert body["balance"] == 0


async def test_create_wallet_requires_authentication(client):
    assert (await client.post("/wallets")).status_code == 401


async def test_second_wallet_for_same_user_is_409(client, headers_for):
    headers = headers_for(uuid4())
    assert (await client.post("/wallets", headers=headers)).status_code == 201
    response = await client.post("/wallets", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "wallet_already_exists"


async def test_concurrent_wallet_creation_makes_exactly_one_wallet(client, headers_for, pool):
    headers = headers_for(uuid4())
    responses = await asyncio.gather(
        client.post("/wallets", headers=headers), client.post("/wallets", headers=headers)
    )
    assert sorted(r.status_code for r in responses) == [201, 409]
    assert await pool.fetchval("SELECT count(*) FROM wallets WHERE kind = 'user'") == 1


async def test_get_my_wallet_and_balance(client, headers_for):
    headers = headers_for(uuid4())
    created = (await client.post("/wallets", headers=headers)).json()

    wallet = await client.get("/wallets/me", headers=headers)
    assert wallet.status_code == 200
    assert wallet.json()["id"] == created["id"]

    balance = await client.get("/wallets/me/balance", headers=headers)
    assert balance.status_code == 200
    assert balance.json() == {"wallet_id": created["id"], "currency": "INR", "balance": 0}


async def test_wallet_routes_are_404_before_a_wallet_exists(client, headers_for):
    headers = headers_for(uuid4())
    for path in ("/wallets/me", "/wallets/me/balance", "/wallets/me/transactions"):
        response = await client.get(path, headers=headers)
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "wallet_not_found"


async def test_each_user_only_sees_their_own_wallet(client, headers_for):
    alice, bob = headers_for(uuid4()), headers_for(uuid4())
    alice_wallet = (await client.post("/wallets", headers=alice)).json()
    bob_wallet = (await client.post("/wallets", headers=bob)).json()
    assert (await client.get("/wallets/me", headers=alice)).json()["id"] == alice_wallet["id"]
    assert (await client.get("/wallets/me", headers=bob)).json()["id"] == bob_wallet["id"]
