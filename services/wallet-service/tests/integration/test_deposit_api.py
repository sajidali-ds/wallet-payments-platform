import asyncio
from uuid import uuid4

import pytest

from app.constants import SYSTEM_WALLET_ID
from app.schemas.wallet import MAX_AMOUNT_PAISE


@pytest.fixture
def admin(headers_for):
    return headers_for(uuid4(), "admin")


async def _new_wallet(client, headers_for):
    headers = headers_for(uuid4())
    wallet = (await client.post("/wallets", headers=headers)).json()
    return headers, wallet["id"]


async def _deposit(client, headers, wallet_id, amount):
    return await client.post(
        f"/wallets/{wallet_id}/deposit", json={"amount": amount}, headers=headers
    )


async def test_admin_deposit_credits_the_wallet(
    client, headers_for, admin, pool, assert_ledger_consistent
):
    user, wallet_id = await _new_wallet(client, headers_for)

    response = await _deposit(client, admin, wallet_id, 5000)
    assert response.status_code == 201
    body = response.json()
    assert body["amount"] == 5000
    assert body["balance_after"] == 5000

    assert (await client.get("/wallets/me/balance", headers=user)).json()["balance"] == 5000
    # The money came from the system wallet, which is why it is now negative.
    system_balance = await pool.fetchval(
        "SELECT balance FROM wallets WHERE id = $1", SYSTEM_WALLET_ID
    )
    assert system_balance == -5000
    entries = await pool.fetch(
        "SELECT wallet_id::text AS wallet_id, amount FROM ledger_entries WHERE transfer_id = $1",
        body["transfer_id"],
    )
    assert {(e["wallet_id"], e["amount"]) for e in entries} == {
        (str(SYSTEM_WALLET_ID), -5000),
        (wallet_id, 5000),
    }
    await assert_ledger_consistent()


async def test_deposits_accumulate(client, headers_for, admin, assert_ledger_consistent):
    user, wallet_id = await _new_wallet(client, headers_for)
    for amount in (100, 250, 650):
        assert (await _deposit(client, admin, wallet_id, amount)).status_code == 201
    assert (await client.get("/wallets/me/balance", headers=user)).json()["balance"] == 1000
    await assert_ledger_consistent()


async def test_regular_user_cannot_deposit(client, headers_for, assert_ledger_consistent):
    user, wallet_id = await _new_wallet(client, headers_for)
    response = await _deposit(client, user, wallet_id, 5000)
    assert response.status_code == 403
    assert (await client.get("/wallets/me/balance", headers=user)).json()["balance"] == 0
    await assert_ledger_consistent()


async def test_deposit_requires_authentication(client, headers_for):
    _, wallet_id = await _new_wallet(client, headers_for)
    assert (await _deposit(client, {}, wallet_id, 5000)).status_code == 401


async def test_deposit_to_unknown_wallet_is_404(client, admin):
    response = await _deposit(client, admin, uuid4(), 5000)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "wallet_not_found"


async def test_cannot_deposit_into_the_system_wallet(client, admin, pool):
    assert (await _deposit(client, admin, SYSTEM_WALLET_ID, 5000)).status_code == 404
    assert await pool.fetchval("SELECT count(*) FROM transfers") == 0


async def test_deposit_with_malformed_wallet_id_is_422(client, admin):
    assert (await _deposit(client, admin, "not-a-uuid", 5000)).status_code == 422


@pytest.mark.parametrize("amount", [0, -5, 10.5, "100", True, None, MAX_AMOUNT_PAISE + 1])
async def test_invalid_amounts_are_rejected_and_nothing_is_written(
    client, headers_for, admin, pool, amount
):
    _, wallet_id = await _new_wallet(client, headers_for)
    assert (await _deposit(client, admin, wallet_id, amount)).status_code == 422
    assert await pool.fetchval("SELECT count(*) FROM transfers") == 0


async def test_concurrent_deposits_are_all_applied_exactly_once(
    client, headers_for, admin, pool, assert_ledger_consistent
):
    user, wallet_id = await _new_wallet(client, headers_for)
    responses = await asyncio.gather(*[_deposit(client, admin, wallet_id, 100) for _ in range(50)])

    assert [r.status_code for r in responses] == [201] * 50
    assert (await client.get("/wallets/me/balance", headers=user)).json()["balance"] == 5000
    entry_count = await pool.fetchval(
        "SELECT count(*) FROM ledger_entries WHERE wallet_id = $1", wallet_id
    )
    assert entry_count == 50
    await assert_ledger_consistent()
