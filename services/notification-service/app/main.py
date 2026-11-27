import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.config import get_settings
from app.consumers.runner import run_consumer
from app.consumers.topology import Topology
from app.consumers.transfer_consumer import TransferEventConsumer
from app.db import create_pool
from app.exceptions import AppError, app_error_handler
from app.logging_config import configure_logging
from app.middleware.metrics import MetricsMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.routers import health, metrics, notifications

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.pool = await create_pool(settings.database_url)

    topology = Topology(
        exchange=settings.exchange_name,
        queue=settings.queue_name,
        max_retries=settings.max_retries,
        retry_base_delay_ms=settings.retry_base_delay_ms,
    )
    consumer = TransferEventConsumer(
        app.state.pool, topology, prefetch_count=settings.prefetch_count
    )
    app.state.consumer = consumer
    stop = asyncio.Event()
    consumer_task = asyncio.create_task(run_consumer(consumer, settings.rabbitmq_url, stop))

    log.info("service_started", service=settings.service_name)
    try:
        yield
    finally:
        stop.set()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(consumer_task, timeout=15)
        await app.state.pool.close()
        log.info("service_stopped", service=settings.service_name)


def create_app() -> FastAPI:
    configure_logging(get_settings().log_level)
    app = FastAPI(title="notification-service", lifespan=lifespan)
    # The last middleware added is the outermost: the request id exists before anything else runs.
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(health.router)
    app.include_router(notifications.router)
    app.include_router(metrics.router)
    return app


app = create_app()
