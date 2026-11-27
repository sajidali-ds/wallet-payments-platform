import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from redis.asyncio import Redis

from app.cache.balance_cache import BalanceCache
from app.cache.guard import RedisGuard
from app.cache.rate_limiter import RateLimiter, RateLimits
from app.config import get_settings
from app.db import create_pool
from app.exceptions import AppError, app_error_handler
from app.logging_config import configure_logging
from app.middleware.metrics import MetricsMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.outbox.rabbit import RabbitBroker
from app.outbox.relay import OutboxRelay
from app.routers import admin, health, metrics, transfers, wallets

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.pool = await create_pool(settings.database_url)

    # Redis: creating the client does not connect, so the service starts even if Redis is down.
    # Short timeouts keep a dead Redis from slowing requests; one shared guard = one circuit
    # breaker for everything that uses Redis.
    redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=0.25,
        socket_timeout=0.25,
    )
    guard = RedisGuard()
    app.state.redis = redis
    app.state.balance_cache = BalanceCache(
        redis, guard, ttl_seconds=settings.balance_cache_ttl_seconds
    )
    app.state.rate_limiter = RateLimiter(redis, guard)

    # The relay is a background task of this service. It starts even if RabbitMQ is down (it
    # retries with backoff), and several instances of the service can run it at once safely
    # because of FOR UPDATE SKIP LOCKED.
    stop = asyncio.Event()
    broker = RabbitBroker(settings.rabbitmq_url, settings.exchange_name)
    relay_task = None
    if settings.outbox_enabled:
        relay = OutboxRelay(
            app.state.pool,
            broker,
            batch_size=settings.outbox_batch_size,
            poll_interval=settings.outbox_poll_interval_seconds,
        )
        relay_task = asyncio.create_task(relay.run(stop))

    log.info("service_started", service=settings.service_name)
    try:
        yield
    finally:
        stop.set()
        if relay_task is not None:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(relay_task, timeout=15)
        await broker.close()
        with contextlib.suppress(Exception):
            await redis.aclose()
        await app.state.pool.close()
        log.info("service_stopped", service=settings.service_name)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="wallet-service", lifespan=lifespan)

    # Safe defaults (cache and limiter disabled) so the app also works without a lifespan,
    # e.g. in tests. The lifespan replaces the first three with the real Redis-backed ones.
    app.state.redis = None
    app.state.balance_cache = BalanceCache(None)
    app.state.rate_limiter = RateLimiter(None)
    app.state.rate_limits = RateLimits(
        transfers_per_minute=settings.rate_limit_transfers_per_minute,
        reads_per_minute=settings.rate_limit_reads_per_minute,
    )

    # The last middleware added is the outermost: the request id exists before anything else runs.
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(health.router)
    app.include_router(wallets.router)
    app.include_router(transfers.router)
    app.include_router(admin.router)
    app.include_router(metrics.router)
    return app


app = create_app()
