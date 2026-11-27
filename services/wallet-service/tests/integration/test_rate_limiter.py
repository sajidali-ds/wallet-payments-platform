"""The sliding-window limiter against a real Redis."""

import asyncio

from redis.asyncio import Redis

from app.cache.guard import RedisGuard
from app.cache.rate_limiter import RateLimiter


async def test_allows_up_to_the_limit_then_denies(limiter):
    results = [await limiter.hit("alice", limit=3, window_seconds=60) for _ in range(5)]

    assert [r.allowed for r in results] == [True, True, True, False, False]
    assert [r.count for r in results[:3]] == [1, 2, 3]
    assert 0 < results[3].retry_after_ms <= 60_000


async def test_each_key_has_its_own_budget(limiter):
    for _ in range(3):
        await limiter.hit("alice", limit=3, window_seconds=60)
    assert not (await limiter.hit("alice", limit=3, window_seconds=60)).allowed
    assert (await limiter.hit("bob", limit=3, window_seconds=60)).allowed


async def test_parallel_requests_can_never_exceed_the_limit(limiter):
    # 30 requests race for 5 slots. The Lua script is atomic, so exactly 5 get through.
    results = await asyncio.gather(
        *[limiter.hit("alice", limit=5, window_seconds=60) for _ in range(30)]
    )
    assert sum(r.allowed for r in results) == 5


async def test_the_window_slides(limiter):
    # Timing-based (window 1 s): a request counts until it is a full window old.
    assert (await limiter.hit("a", limit=2, window_seconds=1)).allowed  # t = 0.0
    await asyncio.sleep(0.6)
    assert (await limiter.hit("a", limit=2, window_seconds=1)).allowed  # t = 0.6
    assert not (await limiter.hit("a", limit=2, window_seconds=1)).allowed  # full

    await asyncio.sleep(0.5)  # t = 1.1: the first request has left the window, the second has not
    assert (await limiter.hit("a", limit=2, window_seconds=1)).allowed
    assert not (await limiter.hit("a", limit=2, window_seconds=1)).allowed


async def test_denied_requests_are_not_recorded(limiter):
    # Hammering a blocked endpoint must not push the unblock time further away.
    for _ in range(2):
        assert (await limiter.hit("a", limit=2, window_seconds=1)).allowed
    for _ in range(10):
        assert not (await limiter.hit("a", limit=2, window_seconds=1)).allowed
    await asyncio.sleep(1.1)
    assert (await limiter.hit("a", limit=2, window_seconds=1)).allowed


async def test_fails_open_when_redis_is_down(broken_redis):
    limiter = RateLimiter(broken_redis, RedisGuard())
    results = [await limiter.hit("alice", limit=1, window_seconds=60) for _ in range(5)]
    assert all(r.allowed for r in results)  # no Redis, no limiting, but also no outage


async def test_disabled_limiter_allows_everything():
    limiter = RateLimiter(None)
    assert all([(await limiter.hit("a", limit=1, window_seconds=60)).allowed for _ in range(3)])


async def test_circuit_opens_so_a_dead_redis_costs_nothing_per_request(broken_redis: Redis):
    guard = RedisGuard(failure_threshold=3, cooldown_seconds=60)
    limiter = RateLimiter(broken_redis, guard)
    for _ in range(3):
        await limiter.hit("alice", limit=1, window_seconds=60)
    assert guard.is_open
