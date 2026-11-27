import pytest

from app.cache.rate_limiter import RateLimits


@pytest.fixture
async def client(make_client, limiter):
    limits = RateLimits(transfers_per_minute=3, reads_per_minute=4)
    async with make_client(limiter=limiter, rate_limits=limits) as client:
        yield client


async def test_transfers_over_the_limit_get_429_and_move_no_money(
    new_account, transfer, balance_of, pool
):
    alice, bob = await new_account(10_000), await new_account()

    responses = [await transfer(alice, bob.wallet_id, 100) for _ in range(5)]

    assert [r.status_code for r in responses] == [201, 201, 201, 429, 429]
    assert responses[3].json()["error"]["code"] == "rate_limited"
    assert int(responses[3].headers["retry-after"]) >= 1
    assert await balance_of(alice) == 10_000 - 300  # the rejected requests did nothing
    assert await pool.fetchval("SELECT count(*) FROM transfers WHERE type = 'transfer'") == 3


async def test_limits_are_per_user(new_account, transfer):
    alice, bob, carol = await new_account(10_000), await new_account(10_000), await new_account()
    for _ in range(3):
        await transfer(alice, carol.wallet_id, 10)
    assert (await transfer(alice, carol.wallet_id, 10)).status_code == 429

    assert (await transfer(bob, carol.wallet_id, 10)).status_code == 201  # bob has his own budget


async def test_read_endpoints_are_limited_too(client, new_account):
    alice = await new_account(1000)
    statuses = [
        (await client.get("/wallets/me/balance", headers=alice.headers)).status_code
        for _ in range(6)
    ]
    assert statuses == [200, 200, 200, 200, 429, 429]


async def test_unauthenticated_requests_get_401_not_429(client, new_account, redis_client):
    for _ in range(6):
        assert (await client.get("/wallets/me/balance")).status_code == 401
    assert await redis_client.keys("ratelimit:*") == []  # they never touched anyone's budget
