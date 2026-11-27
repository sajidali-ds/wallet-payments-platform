"""Balance cache: hits, invalidation on money movement, the stale-fill race, corruption."""

import asyncio
from uuid import UUID

import pytest

from app.cache.balance_cache import value_key


@pytest.fixture
async def client(make_client, balance_cache):
    # Override: in this module the app runs with the real, Redis-backed cache. The shared
    # `new_account` and `transfer` fixtures use this client too, so transfers invalidate.
    async with make_client(cache=balance_cache) as client:
        yield client


async def _balance(client, account) -> int:
    response = await client.get("/wallets/me/balance", headers=account.headers)
    assert response.status_code == 200
    return response.json()["balance"]


async def test_second_read_is_served_from_redis(new_account, client, balance_cache, pool):
    alice = await new_account(1000)

    assert await _balance(client, alice) == 1000  # miss: reads Postgres and fills the cache
    cached = await balance_cache.get(UUID(alice.user_id))
    assert cached.value["balance"] == 1000

    # Change Postgres behind the application's back. A cache hit never looks at Postgres.
    await pool.execute("UPDATE wallets SET balance = 999 WHERE id = $1", alice.wallet_id)
    assert await _balance(client, alice) == 1000


async def test_entries_expire(new_account, client, redis_client):
    alice = await new_account(1000)
    await _balance(client, alice)
    ttl = await redis_client.ttl(value_key(alice.user_id))
    assert 0 < ttl <= 60


async def test_transfer_invalidates_sender_and_recipient(new_account, transfer, client):
    alice, bob = await new_account(1000), await new_account()
    assert (await _balance(client, alice), await _balance(client, bob)) == (1000, 0)  # warm both

    assert (await transfer(alice, bob.wallet_id, 400)).status_code == 201

    assert await _balance(client, alice) == 600  # not the stale 1000
    assert await _balance(client, bob) == 400


async def test_deposit_invalidates_the_recipient(new_account, client, headers_for):
    bob = await new_account()
    assert await _balance(client, bob) == 0  # warm

    admin = headers_for(None, "admin")
    response = await client.post(
        f"/wallets/{bob.wallet_id}/deposit", json={"amount": 500}, headers=admin
    )
    assert response.status_code == 201

    assert await _balance(client, bob) == 500


async def test_failed_transfer_does_not_disturb_the_cache(
    new_account, transfer, client, balance_cache
):
    alice, bob = await new_account(100), await new_account()
    await _balance(client, alice)

    assert (await transfer(alice, bob.wallet_id, 101)).status_code == 422  # insufficient funds

    assert (await balance_cache.get(UUID(alice.user_id))).value is not None  # still cached
    assert await _balance(client, alice) == 100


async def test_a_late_stale_fill_is_rejected(balance_cache):
    # The classic race, replayed by hand. The reader saw a miss and read Postgres (balance 100).
    user = UUID("00000000-0000-0000-0000-0000000000aa")
    lookup = await balance_cache.get(user)
    assert lookup.value is None

    # Meanwhile a transfer commits (balance is now 70) and invalidates the cache...
    await balance_cache.invalidate([user])
    # ...and only then does the slow reader try to cache what it read BEFORE the transfer.
    stale = {"wallet_id": "w", "currency": "INR", "balance": 100}
    await balance_cache.fill(user, lookup.token, stale)

    assert (await balance_cache.get(user)).value is None  # the stale write was dropped

    fresh = await balance_cache.get(user)  # a reader that started after the invalidation
    current = {"wallet_id": "w", "currency": "INR", "balance": 70}
    await balance_cache.fill(user, fresh.token, current)
    assert (await balance_cache.get(user)).value["balance"] == 70


async def test_corrupted_entry_is_treated_as_a_miss_and_repaired(new_account, client, redis_client):
    alice = await new_account(1000)
    await redis_client.set(value_key(alice.user_id), "{this is not json")

    assert await _balance(client, alice) == 1000  # served from Postgres
    assert "balance" in await redis_client.get(value_key(alice.user_id))  # and repaired


async def test_unknown_wallet_is_404_and_nothing_is_cached(client, headers_for, redis_client):
    headers = headers_for(None)
    response = await client.get("/wallets/me/balance", headers=headers)
    assert response.status_code == 404
    assert await redis_client.keys("balance:*") == []


async def test_cache_is_exact_after_concurrent_transfers_and_reads(new_account, transfer, client):
    alice, bob = await new_account(10_000), await new_account()

    async def keep_reading(account) -> None:
        for _ in range(25):
            await _balance(client, account)

    await asyncio.gather(
        *[transfer(alice, bob.wallet_id, 100) for _ in range(50)],
        keep_reading(alice),
        keep_reading(bob),
        keep_reading(alice),
        keep_reading(bob),
    )

    # Whatever interleaving happened, no stale value may survive the last invalidation.
    assert await _balance(client, alice) == 5_000
    assert await _balance(client, bob) == 5_000
