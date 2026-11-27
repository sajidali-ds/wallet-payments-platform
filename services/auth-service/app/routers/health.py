import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.dependencies import PoolDep, SettingsDep

router = APIRouter(tags=["health"])
log = structlog.get_logger()


@router.get("/health")
async def health(pool: PoolDep, settings: SettingsDep) -> JSONResponse:
    try:
        await pool.fetchval("SELECT 1", timeout=2)
        postgres = "ok"
    except Exception as exc:
        log.warning("health_check_failed", dependency="postgres", error=str(exc))
        postgres = "unavailable"

    healthy = postgres == "ok"
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "service": settings.service_name,
            "checks": {"postgres": postgres},
        },
    )
