"""Metrics of the Redis-backed features (cache, rate limiter) and of the fraud rule."""

import pytest
from prometheus_client import REGISTRY

from app.cache.rate_limiter import RateLimits


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.fixture
async def client(make_client, balance_cache, limiter):
    limits = RateLimits(transfers_per_minute=100, reads_per_minute=3)
    async with make_client(cache=balance_cache, limiter=limiter, rate_limits=limits) as client:
        yield client


async def test_cache_hits_and_misses_are_counted(client, new_account):
    alice = await new_account(1000)
    hits = sample("wallet_balance_cache_total", result="hit")
    misses = sample("wallet_balance_cache_total", result="miss")

    for _ in range(3):  # the first read misses and fills the cache, the next two hit
        assert (await client.get("/wallets/me/balance", headers=alice.headers)).status_code == 200

    assert sample("wallet_balance_cache_total", result="hit") - hits == 2
    assert sample("wallet_balance_cache_total", result="miss") - misses == 1


async def test_rate_limited_requests_are_counted(client, new_account):
    alice = await new_account(1000)
    before = sample("wallet_rate_limited_total", scope="reads")

    for _ in range(5):  # budget is 3 reads per minute
        await client.get("/wallets/me/balance", headers=alice.headers)

    assert sample("wallet_rate_limited_total", scope="reads") - before == 2


async def test_fraud_flags_are_counted(client, new_account, transfer):
    alice, bob = await new_account(1000), await new_account()
    before = sample("wallet_fraud_flags_total")

    for _ in range(7):
        await transfer(alice, bob.wallet_id, 10)

    assert sample("wallet_fraud_flags_total") - before == 1  # one flag per window
