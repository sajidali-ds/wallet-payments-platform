import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

import structlog
from redis.exceptions import RedisError

from app.metrics import REDIS_FAILURES

log = structlog.get_logger()
T = TypeVar("T")


class RedisGuard:
    """Runs Redis operations defensively: an outage degrades features instead of failing requests.

    - Any Redis failure (connection refused, timeout, ...) is swallowed and the caller gets its
      `fallback` value instead ("cache miss", "request allowed").
    - Circuit breaker: after `failure_threshold` failures in a row the guard stops calling Redis
      for `cooldown_seconds`. Without it, every request would wait for a connection timeout while
      Redis is down. After the cooldown the next call is a trial: success closes the circuit.
    """

    def __init__(self, *, failure_threshold: int = 3, cooldown_seconds: float = 5.0) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._failures = 0
        self._open_until = 0.0

    @property
    def is_open(self) -> bool:
        return time.monotonic() < self._open_until

    async def attempt(
        self, operation: Callable[[], Awaitable[T]], *, fallback: T, what: str
    ) -> T:
        if self.is_open:
            return fallback
        try:
            result = await operation()
        except (RedisError, OSError, TimeoutError) as exc:
            self._failures += 1
            REDIS_FAILURES.labels(operation=what).inc()
            log.warning("redis_unavailable", operation=what, error=repr(exc))
            if self._failures >= self._failure_threshold:
                self._open_until = time.monotonic() + self._cooldown_seconds
                log.error("redis_circuit_open", cooldown_seconds=self._cooldown_seconds)
            return fallback
        if self._failures:
            log.info("redis_recovered")
        self._failures = 0
        return result
