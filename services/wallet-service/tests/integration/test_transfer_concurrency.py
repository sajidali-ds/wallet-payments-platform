import asyncio
import random


async def test_100_parallel_transfers_end_with_exact_balances(
    new_account, transfer, balance_of, pool, assert_ledger_consistent
):
    alice, bob = await new_account(10_000), await new_account()

    responses = await asyncio.gather(*[transfer(alice, bob.wallet_id, 100) for _ in range(100)])

    assert [r.status_code for r in responses] == [201] * 100
    assert await balance_of(alice) == 0  # 10_000 - 100 * 100
    assert await balance_of(bob) == 10_000
    assert await pool.fetchval("SELECT count(*) FROM transfers WHERE type = 'transfer'") == 100
    await assert_ledger_consistent()


async def test_parallel_transfers_can_never_overdraw_a_wallet(
    new_account, transfer, balance_of, assert_ledger_consistent
):
    # Alice can afford exactly 50 of the 100 requests. Without the lock, many requests would read
    # "balance = 5000" at the same time and all succeed; the CHECK constraint would then blow up.
    alice, bob = await new_account(5_000), await new_account()

    responses = await asyncio.gather(*[transfer(alice, bob.wallet_id, 100) for _ in range(100)])

    statuses = [r.status_code for r in responses]
    assert statuses.count(201) == 50
    assert statuses.count(422) == 50
    assert {r.json()["error"]["code"] for r in responses if r.status_code == 422} == {
        "insufficient_funds"
    }
    assert await balance_of(alice) == 0
    assert await balance_of(bob) == 5_000
    await assert_ledger_consistent()


async def test_random_parallel_transfers_between_many_accounts_conserve_money(
    new_account, transfer, pool, assert_ledger_consistent
):
    accounts = [await new_account(1_000) for _ in range(5)]
    rng = random.Random(42)  # seeded: a failure is reproducible
    jobs = []
    for _ in range(100):
        sender, receiver = rng.sample(accounts, 2)
        jobs.append(transfer(sender, receiver.wallet_id, rng.randint(1, 400)))

    responses = await asyncio.gather(*jobs)

    assert {r.status_code for r in responses} <= {201, 422}  # never a 500 (deadlock, CHECK, ...)
    assert await pool.fetchval("SELECT SUM(balance) FROM wallets WHERE kind = 'user'") == 5_000
    assert await pool.fetchval("SELECT MIN(balance) FROM wallets WHERE kind = 'user'") >= 0
    await assert_ledger_consistent()
