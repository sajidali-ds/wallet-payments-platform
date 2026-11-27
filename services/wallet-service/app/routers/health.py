import asyncio

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.dependencies import PoolDep, SettingsDep

router = APIRouter(tags=["health"])
log = structlog.get_logger()


@router.get("/health")
async def health(request: Request, pool: PoolDep, settings: SettingsDep) -> JSONResponse:
    try:
        await pool.fetchval("SELECT 1", timeout=2)
        postgres = "ok"
    except Exception as exc:
        log.warning("health_check_failed", dependency="postgres", error=str(exc))
        postgres = "unavailable"

    # Redis is informational: it only powers a cache and a limiter, so an outage must not make
    # Docker mark the service unhealthy (the service is fully functional without it).
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        redis = "disabled"
    else:
        try:
            await asyncio.wait_for(redis_client.ping(), timeout=1)
            redis = "ok"
        except Exception:
            redis = "unavailable"

    healthy = postgres == "ok"
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "service": settings.service_name,
            "checks": {"postgres": postgres, "redis": redis},
        },
    )
