from uuid import uuid4

import pytest

from app.constants import SYSTEM_WALLET_ID
from app.schemas.wallet import MAX_AMOUNT_PAISE


async def test_transfer_moves_money_and_writes_two_ledger_entries(
    new_account, transfer, balance_of, pool, assert_ledger_consistent
):
    alice, bob = await new_account(1000), await new_account()

    response = await transfer(alice, bob.wallet_id, 400)
    assert response.status_code == 201
    body = response.json()
    assert body["amount"] == 400
    assert body["balance_after"] == 600
    assert body["from_wallet_id"] == alice.wallet_id
    assert body["to_wallet_id"] == bob.wallet_id

    assert await balance_of(alice) == 600
    assert await balance_of(bob) == 400
    entries = await pool.fetch(
        "SELECT wallet_id::text AS wallet_id, amount FROM ledger_entries WHERE transfer_id = $1",
        body["transfer_id"],
    )
    assert {(e["wallet_id"], e["amount"]) for e in entries} == {
        (alice.wallet_id, -400),
        (bob.wallet_id, 400),
    }
    await assert_ledger_consistent()


async def test_transfer_appears_in_both_histories(client, new_account, transfer):
    alice, bob = await new_account(1000), await new_account()
    await transfer(alice, bob.wallet_id, 400)

    alice_entry = (await client.get("/wallets/me/transactions", headers=alice.headers)).json()[
        "items"
    ][0]
    bob_entry = (await client.get("/wallets/me/transactions", headers=bob.headers)).json()["items"][
        0
    ]
    assert (alice_entry["type"], alice_entry["amount"], alice_entry["balance_after"]) == (
        "transfer",
        -400,
        600,
    )
    assert alice_entry["counterparty_wallet_id"] == bob.wallet_id
    assert (bob_entry["type"], bob_entry["amount"]) == ("transfer", 400)
    assert bob_entry["counterparty_wallet_id"] == alice.wallet_id


async def test_can_transfer_the_entire_balance(new_account, transfer, balance_of):
    alice, bob = await new_account(500), await new_account()
    assert (await transfer(alice, bob.wallet_id, 500)).status_code == 201
    assert await balance_of(alice) == 0
    assert await balance_of(bob) == 500


async def test_insufficient_funds_is_422_and_changes_nothing(
    new_account, transfer, balance_of, pool, assert_ledger_consistent
):
    alice, bob = await new_account(100), await new_account()
    response = await transfer(alice, bob.wallet_id, 101)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "insufficient_funds"
    assert await balance_of(alice) == 100
    assert await balance_of(bob) == 0
    assert await pool.fetchval("SELECT count(*) FROM transfers WHERE type = 'transfer'") == 0
    await assert_ledger_consistent()


async def test_cannot_transfer_to_yourself(new_account, transfer):
    alice = await new_account(100)
    response = await transfer(alice, alice.wallet_id, 10)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "cannot_transfer_to_self"


async def test_unknown_destination_is_404(new_account, transfer):
    alice = await new_account(100)
    response = await transfer(alice, str(uuid4()), 10)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "wallet_not_found"


async def test_cannot_transfer_into_the_system_wallet(new_account, transfer, balance_of):
    alice = await new_account(100)
    assert (await transfer(alice, str(SYSTEM_WALLET_ID), 10)).status_code == 404
    assert await balance_of(alice) == 100


async def test_sender_without_a_wallet_is_404(client, new_account, headers_for):
    bob = await new_account()
    response = await client.post(
        "/transfers",
        json={"to_wallet_id": bob.wallet_id, "amount": 10},
        headers={**headers_for(uuid4()), "Idempotency-Key": "k"},  # this user never made a wallet
    )
    assert response.status_code == 404


async def test_transfer_requires_authentication(client, new_account):
    bob = await new_account()
    response = await client.post(
        "/transfers",
        json={"to_wallet_id": bob.wallet_id, "amount": 10},
        headers={"Idempotency-Key": "k"},
    )
    assert response.status_code == 401


async def test_sender_cannot_be_chosen_by_the_client(client, new_account, balance_of):
    alice, bob, mallory = await new_account(1000), await new_account(), await new_account()
    response = await client.post(
        "/transfers",
        json={"from_wallet_id": alice.wallet_id, "to_wallet_id": bob.wallet_id, "amount": 500},
        headers={**mallory.headers, "Idempotency-Key": "k"},
    )
    assert response.status_code == 422
    assert await balance_of(alice) == 1000


@pytest.mark.parametrize("amount", [0, -5, 10.5, "100", True, None, MAX_AMOUNT_PAISE + 1])
async def test_invalid_amounts_are_422_and_nothing_is_written(new_account, transfer, pool, amount):
    alice, bob = await new_account(1000), await new_account()
    assert (await transfer(alice, bob.wallet_id, amount)).status_code == 422
    assert await pool.fetchval("SELECT count(*) FROM transfers WHERE type = 'transfer'") == 0


@pytest.mark.parametrize("key", [None, "", "x" * 256, "has space", "bad/char"])
async def test_idempotency_key_is_required_and_validated(client, new_account, key):
    alice, bob = await new_account(1000), await new_account()
    headers = dict(alice.headers)
    if key is not None:
        headers["Idempotency-Key"] = key
    response = await client.post(
        "/transfers", json={"to_wallet_id": bob.wallet_id, "amount": 10}, headers=headers
    )
    assert response.status_code == 422
