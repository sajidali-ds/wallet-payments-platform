from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.config import get_settings
from app.db import create_pool
from app.exceptions import AppError, app_error_handler
from app.logging_config import configure_logging
from app.middleware.metrics import MetricsMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.routers import auth, health, metrics
from app.security import get_dummy_hash

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.pool = await create_pool(settings.database_url)  # one pool for the app's lifetime
    await get_dummy_hash(settings.bcrypt_rounds)  # compute once now, not during the first login
    log.info("service_started", service=settings.service_name)
    try:
        yield
    finally:
        await app.state.pool.close()
        log.info("service_stopped", service=settings.service_name)


def create_app() -> FastAPI:
    configure_logging(get_settings().log_level)
    app = FastAPI(title="auth-service", lifespan=lifespan)
    # The last middleware added is the outermost: the request id exists before anything else runs.
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(metrics.router)
    return app


app = create_app()
