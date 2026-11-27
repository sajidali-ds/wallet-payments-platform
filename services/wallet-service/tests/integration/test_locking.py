import asyncio

import asyncpg


async def test_opposite_direction_transfers_do_not_deadlock(
    new_account, transfer, balance_of, assert_ledger_consistent
):
    alice, bob = await new_account(100_000), await new_account(100_000)

    jobs = []
    for _ in range(50):
        jobs.append(transfer(alice, bob.wallet_id, 100))  # A -> B
        jobs.append(transfer(bob, alice.wallet_id, 70))  # B -> A, interleaved with the above
    responses = await asyncio.wait_for(asyncio.gather(*jobs), timeout=30)

    # With unordered locking Postgres would abort some of these with "deadlock detected" (a 500).
    assert [r.status_code for r in responses] == [201] * 100
    assert await balance_of(alice) == 100_000 - 50 * 100 + 50 * 70
    assert await balance_of(bob) == 100_000 + 50 * 100 - 50 * 70
    await assert_ledger_consistent()


async def test_control_experiment_unordered_locking_does_deadlock(pool, new_account):
    """Shows WHY we lock in id order: take the same two locks in opposite orders and Postgres
    aborts one transaction with a deadlock (after deadlock_timeout, 1 second by default)."""
    alice, bob = await new_account(), await new_account()
    barrier = asyncio.Barrier(2)  # both transactions hold their first lock before asking for more

    async def lock_in_order(first: str, second: str) -> None:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT 1 FROM wallets WHERE id = $1 FOR UPDATE", first)
            await barrier.wait()
            await conn.execute("SELECT 1 FROM wallets WHERE id = $1 FOR UPDATE", second)

    results = await asyncio.gather(
        lock_in_order(alice.wallet_id, bob.wallet_id),
        lock_in_order(bob.wallet_id, alice.wallet_id),
        return_exceptions=True,
    )

    victims = [r for r in results if isinstance(r, asyncpg.DeadlockDetectedError)]
    survivors = [r for r in results if r is None]
    assert len(victims) == 1
    assert len(survivors) == 1
