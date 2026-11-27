import asyncio
import json


async def test_replay_returns_the_same_response_and_moves_money_once(
    new_account, transfer, balance_of, pool, assert_ledger_consistent
):
    alice, bob = await new_account(1000), await new_account()

    first = await transfer(alice, bob.wallet_id, 300, key="order-42")
    second = await transfer(alice, bob.wallet_id, 300, key="order-42")

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert "idempotent-replay" not in first.headers
    assert second.headers["idempotent-replay"] == "true"
    assert await balance_of(alice) == 700
    assert await balance_of(bob) == 300
    assert await pool.fetchval("SELECT count(*) FROM transfers WHERE type = 'transfer'") == 1
    await assert_ledger_consistent()


async def test_ten_concurrent_requests_with_the_same_key_move_money_once(
    new_account, transfer, balance_of, pool, assert_ledger_consistent
):
    alice, bob = await new_account(1000), await new_account()

    responses = await asyncio.gather(
        *[transfer(alice, bob.wallet_id, 100, key="same-key") for _ in range(10)]
    )

    assert [r.status_code for r in responses] == [201] * 10
    assert len({json.dumps(r.json(), sort_keys=True) for r in responses}) == 1  # identical bodies
    replays = [r for r in responses if r.headers.get("idempotent-replay") == "true"]
    assert len(replays) == 9  # exactly one request did the work; the other nine replayed it

    assert await balance_of(alice) == 900  # not 0: money moved ONCE
    assert await balance_of(bob) == 100
    assert await pool.fetchval("SELECT count(*) FROM transfers WHERE type = 'transfer'") == 1
    assert await pool.fetchval("SELECT count(*) FROM idempotency_keys") == 1
    await assert_ledger_consistent()


async def test_same_key_with_a_different_amount_is_rejected(new_account, transfer, balance_of):
    alice, bob = await new_account(1000), await new_account()
    assert (await transfer(alice, bob.wallet_id, 100, key="k")).status_code == 201

    response = await transfer(alice, bob.wallet_id, 200, key="k")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "idempotency_key_reused"
    assert await balance_of(alice) == 900  # only the first request took effect


async def test_same_key_with_a_different_recipient_is_rejected(new_account, transfer, balance_of):
    alice, bob, carol = await new_account(1000), await new_account(), await new_account()
    assert (await transfer(alice, bob.wallet_id, 100, key="k")).status_code == 201

    response = await transfer(alice, carol.wallet_id, 100, key="k")
    assert response.status_code == 422
    assert await balance_of(carol) == 0


async def test_keys_are_scoped_per_user(new_account, transfer, balance_of):
    alice, carol, bob = await new_account(500), await new_account(500), await new_account()
    first = await transfer(alice, bob.wallet_id, 100, key="shared")
    second = await transfer(carol, bob.wallet_id, 100, key="shared")
    assert first.status_code == second.status_code == 201
    assert "idempotent-replay" not in second.headers  # a different user: a genuinely new transfer
    assert await balance_of(bob) == 200


async def test_failed_transfer_is_not_stored_so_the_key_can_be_retried(
    new_account, transfer, client, balance_of, pool, headers_for
):
    alice, bob = await new_account(50), await new_account()
    failed = await transfer(alice, bob.wallet_id, 100, key="retry-me")
    assert failed.status_code == 422
    assert await pool.fetchval("SELECT count(*) FROM idempotency_keys") == 0  # rolled back too

    admin = headers_for(None, "admin")
    await client.post(f"/wallets/{alice.wallet_id}/deposit", json={"amount": 100}, headers=admin)

    retried = await transfer(alice, bob.wallet_id, 100, key="retry-me")
    assert retried.status_code == 201
    assert await balance_of(bob) == 100


async def test_stored_idempotency_row_matches_the_transfer(new_account, transfer, pool):
    alice, bob = await new_account(1000), await new_account()
    body = (await transfer(alice, bob.wallet_id, 250, key="row-check")).json()

    row = await pool.fetchrow(
        """
        SELECT request_hash, response_status, response_body::text AS body, transfer_id::text AS tid
        FROM idempotency_keys WHERE key = 'row-check'
        """
    )
    assert len(row["request_hash"]) == 64
    assert row["response_status"] == 201
    assert row["tid"] == body["transfer_id"]
    assert json.loads(row["body"]) == body
