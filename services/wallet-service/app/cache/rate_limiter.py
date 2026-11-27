import uuid
from dataclasses import dataclass

from redis.asyncio import Redis

from app.cache.guard import RedisGuard

# SLIDING WINDOW LOG, in one atomic Lua script (Redis runs a script without interleaving other
# commands, so concurrent requests cannot both squeeze under the limit).
# Each allowed request is stored in a sorted set (score = time in ms). To decide: drop entries older
# than the window, count what is left, allow if under the limit. Denied requests are NOT recorded,
# so hammering a blocked endpoint does not extend the block. Time comes from the Redis server
# (TIME), so several app instances share one clock.
_SCRIPT = """
local t = redis.call('TIME')
local now_ms = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local window_ms = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])

redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms - window_ms)
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    return {0, count, tonumber(oldest[2]) + window_ms - now_ms}
end
redis.call('ZADD', KEYS[1], now_ms, ARGV[3])
redis.call('PEXPIRE', KEYS[1], window_ms)
return {1, count + 1, 0}
"""


@dataclass(frozen=True)
class RateLimits:
    transfers_per_minute: int
    reads_per_minute: int


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    count: int  # requests in the current window, including this one if allowed
    retry_after_ms: int  # when denied: how long until the oldest request leaves the window


_ALLOWED = RateLimitResult(allowed=True, count=0, retry_after_ms=0)


class RateLimiter:
    """Per-key sliding-window limiter.

    FAILS OPEN: if Redis is unavailable the request is allowed. For a payments API that is the
    right default for a limiter (an outage must not stop customers paying), because the real
    protections (balance checks, idempotency, constraints) live in Postgres, not here.
    With redis=None the limiter is disabled.
    """

    def __init__(self, redis: Redis | None, guard: RedisGuard | None = None) -> None:
        self._guard = guard or RedisGuard()
        self._script = redis.register_script(_SCRIPT) if redis is not None else None

    async def hit(self, key: str, *, limit: int, window_seconds: float) -> RateLimitResult:
        script = self._script
        if script is None:
            return _ALLOWED

        async def operation() -> RateLimitResult:
            allowed, count, retry_after_ms = await script(
                keys=[f"ratelimit:{key}"],
                args=[int(window_seconds * 1000), limit, uuid.uuid4().hex],
            )
            return RateLimitResult(bool(allowed), int(count), int(retry_after_ms))

        return await self._guard.attempt(operation, fallback=_ALLOWED, what="rate_limit")
