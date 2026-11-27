import asyncio

from redis.exceptions import ConnectionError as RedisConnectionError

from app.cache.guard import RedisGuard


class Flaky:
    """An operation that fails until `heal()` is called, and counts how often it was invoked."""

    def __init__(self) -> None:
        self.calls = 0
        self.healthy = False

    def heal(self) -> None:
        self.healthy = True

    async def __call__(self) -> str:
        self.calls += 1
        if not self.healthy:
            raise RedisConnectionError("connection refused")
        return "real value"


async def test_returns_the_real_result_when_redis_works():
    operation = Flaky()
    operation.heal()
    assert await RedisGuard().attempt(operation, fallback="fallback", what="t") == "real value"


async def test_returns_the_fallback_instead_of_raising_when_redis_fails():
    guard = RedisGuard()
    assert await guard.attempt(Flaky(), fallback="fallback", what="t") == "fallback"


async def test_circuit_opens_after_repeated_failures_and_stops_calling_redis():
    guard = RedisGuard(failure_threshold=3, cooldown_seconds=60)
    operation = Flaky()

    for _ in range(3):
        await guard.attempt(operation, fallback=None, what="t")
    assert guard.is_open
    assert operation.calls == 3

    for _ in range(10):  # circuit open: these never reach Redis (no connection timeouts paid)
        await guard.attempt(operation, fallback=None, what="t")
    assert operation.calls == 3


async def test_circuit_closes_again_once_redis_recovers():
    guard = RedisGuard(failure_threshold=2, cooldown_seconds=0.1)
    operation = Flaky()
    for _ in range(2):
        await guard.attempt(operation, fallback=None, what="t")
    assert guard.is_open

    operation.heal()
    await asyncio.sleep(0.15)  # cooldown over: the next call is a trial

    assert await guard.attempt(operation, fallback="fallback", what="t") == "real value"
    assert not guard.is_open


async def test_failed_trial_reopens_the_circuit():
    guard = RedisGuard(failure_threshold=2, cooldown_seconds=0.1)
    operation = Flaky()
    for _ in range(2):
        await guard.attempt(operation, fallback=None, what="t")
    await asyncio.sleep(0.15)

    await guard.attempt(operation, fallback=None, what="t")  # trial fails: still broken
    assert guard.is_open
