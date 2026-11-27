"""With Redis dead, the system must keep working correctly: Postgres stays the source of truth."""

import pytest
from prometheus_client import REGISTRY

from app.cache.balance_cache import BalanceCache
from app.cache.guard import RedisGuard
from app.cache.rate_limiter import RateLimiter, RateLimits


@pytest.fixture
def guard():
    return RedisGuard(failure_threshold=3, cooldown_seconds=60)


@pytest.fixture
async def client(make_client, broken_redis, guard):
    # The real cache and limiter, wired to a Redis that refuses every connection.
    # The limits are tiny: if the limiter did NOT fail open, these tests would see 429s.
    async with make_client(
        cache=BalanceCache(broken_redis, guard),
        limiter=RateLimiter(broken_redis, guard),
        rate_limits=RateLimits(transfers_per_minute=1, reads_per_minute=1),
        redis=broken_redis,
    ) as client:
        yield client


async def test_transfers_still_work_and_are_not_rate_limited(
    new_account, transfer, balance_of, assert_ledger_consistent
):
    alice, bob = await new_account(10_000), await new_account()

    statuses = [(await transfer(alice, bob.wallet_id, 100)).status_code for _ in range(10)]

    assert statuses == [201] * 10  # the limiter failed open
    assert await balance_of(alice) == 9_000
    assert await balance_of(bob) == 1_000
    await assert_ledger_consistent()


async def test_balance_comes_from_postgres_and_is_never_stale(new_account, transfer, client):
    alice, bob = await new_account(1000), await new_account()

    async def balance(account) -> int:
        response = await client.get("/wallets/me/balance", headers=account.headers)
        assert response.status_code == 200
        return response.json()["balance"]

    assert await balance(alice) == 1000
    await transfer(alice, bob.wallet_id, 400)
    assert await balance(alice) == 600
    assert await balance(bob) == 400


async def test_circuit_breaker_opens_so_requests_stay_fast(new_account, transfer, guard):
    alice, bob = await new_account(10_000), await new_account()
    for _ in range(5):
        await transfer(alice, bob.wallet_id, 100)
    assert guard.is_open  # after a few failures Redis is no longer even attempted


async def test_fraud_rule_does_not_depend_on_redis(new_account, transfer, pool):
    alice, bob = await new_account(1000), await new_account()
    for _ in range(6):
        assert (await transfer(alice, bob.wallet_id, 10)).status_code == 201
    assert await pool.fetchval("SELECT count(*) FROM fraud_flags") == 1  # Postgres-only rule


async def test_health_reports_redis_unavailable_but_stays_200(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["checks"] == {"postgres": "ok", "redis": "unavailable"}


async def test_redis_failures_and_unavailable_reads_are_counted(new_account, client):
    alice = await new_account(1000)
    failed_before = (
        REGISTRY.get_sample_value("wallet_redis_failures_total", {"operation": "balance_get"})
        or 0.0
    )
    unavailable_before = REGISTRY.get_sample_value(
        "wallet_balance_cache_total", {"result": "unavailable"}
    )

    response = await client.get("/wallets/me/balance", headers=alice.headers)
    assert response.status_code == 200  # served from Postgres despite the failure

    failed_after = REGISTRY.get_sample_value(
        "wallet_redis_failures_total", {"operation": "balance_get"}
    )
    unavailable_after = REGISTRY.get_sample_value(
        "wallet_balance_cache_total", {"result": "unavailable"}
    )
    assert failed_after - failed_before == 1
    assert unavailable_after - unavailable_before == 1
