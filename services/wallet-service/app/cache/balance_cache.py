import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis

from app.cache.guard import RedisGuard

GENERATION_TTL_SECONDS = 24 * 3600


def value_key(user_id: uuid.UUID | str) -> str:
    return f"balance:{user_id}"


def generation_key(user_id: uuid.UUID | str) -> str:
    return f"balance_gen:{user_id}"


# Compare-and-set: store the value only if the generation is still the one the reader saw.
_FILL_SCRIPT = """
local generation = redis.call('GET', KEYS[2]) or '0'
if generation == ARGV[1] then
    redis.call('SET', KEYS[1], ARGV[2], 'EX', tonumber(ARGV[3]))
    return 1
end
return 0
"""


@dataclass(frozen=True)
class CacheLookup:
    value: dict[str, Any] | None  # the cached balance document, or None on a miss
    token: str | None  # generation seen at lookup time; None = Redis unavailable, do not fill


_UNAVAILABLE = CacheLookup(value=None, token=None)


def _decode(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None  # a corrupted entry is just a miss; the next fill repairs it
    return value if isinstance(value, dict) else None


class BalanceCache:
    """Cache-aside cache for GET /wallets/me/balance. The database is always the truth.

    SAFETY RULES
      * Only the read endpoint uses it. Transfers never read the cache: their balance check
        uses the row they have locked in Postgres.
      * Invalidated AFTER a transfer commits (never before: a reader could re-cache the old value).
      * TTL: if an invalidation is ever lost (Redis blip), the entry still dies within `ttl`.

    THE CLASSIC RACE, AND HOW THE GENERATION COUNTER CLOSES IT
      reader: cache miss -> reads balance 100 from Postgres ...
      writer: commits a transfer (balance 70) and deletes the cache entry
      reader: ... writes 100 into the cache.   <- stale until the TTL, with plain delete-on-write
    So every invalidation also bumps a per-user generation number. A reader remembers the
    generation it saw BEFORE reading Postgres, and its cache write only happens if the generation
    is still the same. A late, stale write is rejected.

    With redis=None the cache is disabled: every lookup is a miss and writes do nothing.
    """

    def __init__(
        self, redis: Redis | None, guard: RedisGuard | None = None, *, ttl_seconds: int = 60
    ) -> None:
        self._redis = redis
        self._guard = guard or RedisGuard()
        self._ttl_seconds = ttl_seconds
        self._fill_script = redis.register_script(_FILL_SCRIPT) if redis is not None else None

    async def get(self, user_id: uuid.UUID) -> CacheLookup:
        redis = self._redis
        if redis is None:
            return _UNAVAILABLE

        async def operation() -> CacheLookup:
            # MGET reads both keys in one atomic step, so value and generation are consistent.
            raw_value, raw_generation = await redis.mget(
                value_key(user_id), generation_key(user_id)
            )
            return CacheLookup(_decode(raw_value), raw_generation or "0")

        return await self._guard.attempt(operation, fallback=_UNAVAILABLE, what="balance_get")

    async def fill(self, user_id: uuid.UUID, token: str | None, value: dict[str, Any]) -> None:
        script = self._fill_script
        if script is None or token is None:
            return

        async def operation() -> None:
            await script(
                keys=[value_key(user_id), generation_key(user_id)],
                args=[token, json.dumps(value), self._ttl_seconds],
            )

        await self._guard.attempt(operation, fallback=None, what="balance_fill")

    async def invalidate(self, user_ids: Iterable[uuid.UUID]) -> None:
        redis = self._redis
        ids = list(user_ids)
        if redis is None or not ids:
            return

        async def operation() -> None:
            # MULTI/EXEC: bump the generation and delete the value as one atomic step.
            async with redis.pipeline(transaction=True) as pipe:
                for user_id in ids:
                    pipe.incr(generation_key(user_id))
                    pipe.expire(generation_key(user_id), GENERATION_TTL_SECONDS)
                    pipe.delete(value_key(user_id))
                await pipe.execute()

        await self._guard.attempt(operation, fallback=None, what="balance_invalidate")
